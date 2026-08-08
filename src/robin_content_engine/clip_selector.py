from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .highlight_scoring import WindowScore


class ClipSelectionError(Exception):
    pass


@dataclass(frozen=True)
class WindowSelectorConfig:
    """Configurable, not buried. Durations are in seconds; internally
    converted to a whole number of score-timeline bins."""

    min_clip_seconds: float = 15.0
    max_clip_seconds: float = 60.0
    duration_step_seconds: float = 5.0
    overlap_iou_threshold: float = 0.35
    max_candidates_before_dedup: int = 50


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


def _interval_iou(a: HighlightCandidate, b: HighlightCandidate) -> float:
    start = max(a.start_seconds, b.start_seconds)
    end = min(a.end_seconds, b.end_seconds)
    intersection = max(0.0, end - start)
    union = a.duration_seconds + b.duration_seconds - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def generate_candidate_windows(
    window_scores: Sequence[WindowScore],
    config: WindowSelectorConfig | None = None,
) -> list[HighlightCandidate]:
    """Cumulative-sum sliding-window best-subwindow search (the AutoShorts
    idea, reimplemented in plain NumPy - no torch, no GPU).

    Tests every duration from min to max (stepped by duration_step_seconds),
    and for each duration finds the single highest-scoring start position via
    an O(n) cumsum trick. Candidates are NOT locked to scene boundaries - a
    window can start/end mid-scene and include lead-in/lead-out context
    around a peak, since it searches the raw per-bin score timeline rather
    than one window per detected scene. Boundary clamping is automatic: the
    search space only ever contains positions fully inside [0, n_bins).

    Each candidate's score is the MEAN per-bin score over its span, not the
    raw sum - this keeps candidates of different durations comparable
    (a longer window has a larger sum just from covering more bins).
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
    scores = np.array([w.final_score for w in window_scores], dtype=np.float64)
    cumsum = np.concatenate(([0.0], np.cumsum(scores)))

    min_bins = max(1, round(config.min_clip_seconds / bin_seconds))
    max_bins = min(max(min_bins, round(config.max_clip_seconds / bin_seconds)), n)
    step_bins = max(1, round(config.duration_step_seconds / bin_seconds))

    if min_bins > n:
        return []

    candidates: list[HighlightCandidate] = []
    for duration_bins in range(min_bins, max_bins + 1, step_bins):
        window_sums = cumsum[duration_bins:] - cumsum[:-duration_bins]
        if window_sums.size == 0:
            continue
        best_start = int(np.argmax(window_sums))
        best_mean = float(window_sums[best_start]) / duration_bins
        end_bin = best_start + duration_bins

        segment = window_scores[best_start:end_bin]
        peak = max(segment, key=lambda w: w.final_score)

        candidates.append(
            HighlightCandidate(
                start_seconds=window_scores[best_start].window.start_seconds,
                end_seconds=window_scores[end_bin - 1].window.end_seconds,
                score=best_mean,
                audio_score=float(np.mean([w.audio_score for w in segment])),
                motion_score=float(np.mean([w.motion_score for w in segment])),
                scene_signal=float(np.mean([w.scene_signal for w in segment])),
                reason=peak.reason,
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.start_seconds))
    return candidates[: config.max_candidates_before_dedup]


def suppress_overlaps(
    candidates: Sequence[HighlightCandidate],
    iou_threshold: float,
    top_n: int,
) -> list[HighlightCandidate]:
    """Greedy highest-score-first temporal-IoU suppression. `candidates`
    must already be sorted best-first (as generate_candidate_windows
    returns them) - this function does not re-sort, so the caller's
    ordering is what determines which of two overlapping candidates wins.
    """
    if top_n <= 0:
        return []
    selected: list[HighlightCandidate] = []
    for candidate in candidates:
        if len(selected) >= top_n:
            break
        if all(_interval_iou(candidate, kept) <= iou_threshold for kept in selected):
            selected.append(candidate)
    return selected
