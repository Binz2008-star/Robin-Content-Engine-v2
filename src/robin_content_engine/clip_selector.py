from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .highlight_scoring import WindowScore, describe_reason


class ClipSelectionError(Exception):
    pass


# Real-timestamp duration validation tolerance. Guards only against
# negligible floating-point accumulation in TimeWindow boundaries, not
# against genuine sub-second shortfalls like a truncated final bin.
_DURATION_TOLERANCE_SECONDS = 1e-6


@dataclass(frozen=True)
class WindowSelectorConfig:
    """Configurable, not buried. Durations are in seconds; internally
    converted to a whole number of score-timeline bins.

    There is deliberately no cap on the candidate pool before
    suppress_overlaps() runs (see generate_candidate_windows() for why an
    earlier max_candidates_before_dedup field was removed rather than
    just raised) - suppress_overlaps() itself already stops as soon as
    top_n distinct candidates are accepted, so it is the only place a
    result-size bound belongs.
    """

    min_clip_seconds: float = 15.0
    max_clip_seconds: float = 60.0
    duration_step_seconds: float = 5.0
    overlap_iou_threshold: float = 0.35
    containment_threshold: float = 0.50


@dataclass(frozen=True)
class HighlightCandidate:
    start_seconds: float
    end_seconds: float
    score: float
    audio_score: float
    motion_score: float
    scene_signal: float
    reason: str

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def _intersection_seconds(a: HighlightCandidate, b: HighlightCandidate) -> float:
    start = max(a.start_seconds, b.start_seconds)
    end = min(a.end_seconds, b.end_seconds)
    return max(0.0, end - start)


def _interval_iou(a: HighlightCandidate, b: HighlightCandidate) -> float:
    intersection = _intersection_seconds(a, b)
    union = a.duration_seconds + b.duration_seconds - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _containment_ratio(a: HighlightCandidate, b: HighlightCandidate) -> float:
    """Fraction of the SHORTER candidate's duration that overlaps the other.

    Catches a near-duplicate case IoU alone can miss: two different-duration
    windows covering essentially the same event, where IoU stays just under
    threshold only because its denominator (the union) grows with the
    longer window. Confirmed against a real case (job 19): 389-404s (15s)
    vs. 378-398s (20s) had IoU ~= 0.346 (just under a 0.35 threshold) but
    9 of the shorter clip's 15 seconds (60%) were duplicated inside the
    other - a real duplicate that IoU alone let through.
    """
    shorter_duration = min(a.duration_seconds, b.duration_seconds)
    if shorter_duration <= 0:
        return 0.0
    return _intersection_seconds(a, b) / shorter_duration


def _is_near_duplicate(
    a: HighlightCandidate,
    b: HighlightCandidate,
    iou_threshold: float,
    containment_threshold: float,
) -> bool:
    """True if b should be rejected as a duplicate of already-accepted a.

    Two independent criteria, either one sufficient: classic temporal IoU
    (catches near-equal-span overlaps), and containment ratio (catches a
    short candidate mostly swallowed by a longer one, which a wide IoU
    denominator can let slip through - see _containment_ratio)."""
    if _interval_iou(a, b) > iou_threshold:
        return True
    return _containment_ratio(a, b) >= containment_threshold


def generate_candidate_windows(
    window_scores: Sequence[WindowScore],
    config: WindowSelectorConfig | None = None,
) -> list[HighlightCandidate]:
    """Cumulative-sum sliding-window search (the AutoShorts idea, reimplemented
    in plain NumPy - no torch, no GPU) over EVERY valid start position for
    EVERY configured duration - not just the single best start per duration.

    A source video routinely contains several genuinely separate highlights;
    keeping only np.argmax() per duration would cluster nearly all candidates
    around whichever single event is strongest, silently discarding the
    others before overlap suppression ever runs. Instead: build a candidate
    for every valid (duration, start) pair and rank the FULL pool globally by
    score - the complete ranked pool, not a truncated prefix of it, is what
    gets handed to suppress_overlaps(). On a long source, the highest-scoring
    ~50 raw candidates can easily all be overlapping variants of one single
    dominant event (many durations x many start offsets all covering the
    same active region); truncating the pool to a fixed size before dedup
    would discard every genuinely distinct lower-scoring event before
    suppress_overlaps() ever got a chance to consider them - which is
    exactly what a prior version of this function did via a
    max_candidates_before_dedup cap, confirmed against a real ~409s capture
    that returned only 2 near-duplicate candidates instead of 5 distinct
    ones. suppress_overlaps() already stops as soon as top_n distinct
    candidates are accepted, so it - not this function - is the right place
    for a result-size bound; ranking/dedup here is comparatively cheap next
    to the scene/audio/motion feature extraction that produced window_scores
    in the first place, so no pool-size cap is reintroduced.

    Candidates are NOT locked to scene boundaries - a window can start/end
    mid-scene and include lead-in/lead-out context around a peak, since it
    searches the raw per-bin score timeline rather than one window per
    detected scene. Boundary clamping is automatic: the search space only
    ever contains positions fully inside [0, n_bins).

    Each candidate's score is the MEAN per-bin score over its span, not the
    raw sum - this keeps candidates of different durations comparable (a
    longer window has a larger sum just from covering more bins).

    min_clip_seconds/max_clip_seconds are converted to a bin COUNT once,
    using the first window's width as the nominal bin size - but
    generate_time_windows() truncates the final bin when the source
    duration isn't an exact multiple of that width (e.g. a 26.555s source
    at a 1.0s grid ends with a 0.555s final bin, not a full 1.0s one). A
    candidate spanning the configured bin COUNT can therefore span LESS
    real time than min_clip_seconds if it includes that truncated bin, or
    more than max_clip_seconds in principle. Bin count decides which
    durations to search; every candidate's REAL timestamp span
    (end_seconds - start_seconds) is what actually gets validated against
    min/max_clip_seconds before it's kept, so the configured real-time
    contract can never be silently violated by a non-uniform final bin.
    """
    config = config or WindowSelectorConfig()
    if not window_scores:
        return []

    bin_seconds = window_scores[0].window.end_seconds - window_scores[0].window.start_seconds
    if bin_seconds <= 0:
        raise ClipSelectionError("window_scores must have positive-width windows")
    if config.min_clip_seconds <= 0 or config.max_clip_seconds < config.min_clip_seconds:
        raise ClipSelectionError("min_clip_seconds must be positive and <= max_clip_seconds")

    n = len(window_scores)
    final_cumsum = _prefix_sum([w.final_score for w in window_scores])
    audio_cumsum = _prefix_sum([w.audio_score for w in window_scores])
    motion_cumsum = _prefix_sum([w.motion_score for w in window_scores])
    scene_cumsum = _prefix_sum([w.scene_signal for w in window_scores])

    min_bins = max(1, round(config.min_clip_seconds / bin_seconds))
    max_bins = min(max(min_bins, round(config.max_clip_seconds / bin_seconds)), n)
    step_bins = max(1, round(config.duration_step_seconds / bin_seconds))

    if min_bins > n:
        return []

    candidates: list[HighlightCandidate] = []
    for duration_bins in range(min_bins, max_bins + 1, step_bins):
        score_means = _sliding_means(final_cumsum, duration_bins)
        if score_means.size == 0:
            continue
        audio_means = _sliding_means(audio_cumsum, duration_bins)
        motion_means = _sliding_means(motion_cumsum, duration_bins)
        scene_means = _sliding_means(scene_cumsum, duration_bins)

        for start in range(score_means.shape[0]):
            end_bin = start + duration_bins
            start_seconds = window_scores[start].window.start_seconds
            end_seconds = window_scores[end_bin - 1].window.end_seconds
            actual_duration = end_seconds - start_seconds

            # Real-timestamp check, independent of the nominal bin count:
            # a truncated final bin can make a candidate's real span fall
            # short of (or, in principle, exceed) the configured bounds
            # even though its bin COUNT matched. Never pad/extend past the
            # source's real duration to force a fit - just drop it.
            if actual_duration < config.min_clip_seconds - _DURATION_TOLERANCE_SECONDS:
                continue
            if actual_duration > config.max_clip_seconds + _DURATION_TOLERANCE_SECONDS:
                continue

            audio_mean = float(audio_means[start])
            motion_mean = float(motion_means[start])
            scene_mean = float(scene_means[start])
            candidates.append(
                HighlightCandidate(
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    score=float(score_means[start]),
                    audio_score=audio_mean,
                    motion_score=motion_mean,
                    scene_signal=scene_mean,
                    reason=describe_reason(audio_mean, motion_mean, scene_mean),
                )
            )

    candidates.sort(key=lambda c: (-c.score, c.start_seconds))
    return candidates


def _prefix_sum(values: Sequence[float]) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(np.asarray(values, dtype=np.float64))))


def _sliding_means(cumsum: np.ndarray, duration_bins: int) -> np.ndarray:
    """Mean of every valid contiguous span of `duration_bins` bins, via a
    single O(n) cumsum difference rather than an O(n * duration_bins) loop."""
    sums = cumsum[duration_bins:] - cumsum[:-duration_bins]
    return np.asarray(sums / duration_bins, dtype=np.float64)


def suppress_overlaps(
    candidates: Sequence[HighlightCandidate],
    iou_threshold: float,
    top_n: int,
    containment_threshold: float = 0.50,
) -> list[HighlightCandidate]:
    """Greedy highest-score-first near-duplicate suppression. `candidates`
    must already be sorted best-first (as generate_candidate_windows
    returns them) - this function does not re-sort, so the caller's
    ordering is what determines which of two overlapping candidates wins.

    A candidate is rejected as a duplicate of an already-accepted one if
    EITHER their temporal IoU exceeds `iou_threshold` OR the shorter one's
    duration is at least `containment_threshold`-covered by the other (see
    _containment_ratio) - IoU alone missed a real case where a short clip
    was 60% contained in a longer one but their IoU (~0.35's denominator
    growing with the longer span) stayed just under threshold.
    """
    if top_n <= 0:
        return []
    selected: list[HighlightCandidate] = []
    for candidate in candidates:
        if len(selected) >= top_n:
            break
        if not any(
            _is_near_duplicate(candidate, kept, iou_threshold, containment_threshold)
            for kept in selected
        ):
            selected.append(candidate)
    return selected
