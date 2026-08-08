from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.clip_selector import (  # noqa: E402
    ClipSelectionError,
    HighlightCandidate,
    WindowSelectorConfig,
    _interval_iou,
    generate_candidate_windows,
    suppress_overlaps,
)
from robin_content_engine.highlight_features import TimeWindow  # noqa: E402
from robin_content_engine.highlight_scoring import WindowScore  # noqa: E402


def _multi_peak_score_windows(n: int, peak_regions: list[tuple[int, int, float]]):
    """Build an n-bin timeline with several separated elevated regions, each
    `(start_bin, end_bin, value)` - a few consecutive bins per event, like a
    real few-second gameplay spike, rather than a single isolated sample."""
    scores = []
    for i in range(n):
        value = 0.0
        for start, end, peak_value in peak_regions:
            if start <= i < end:
                value = peak_value
                break
        scores.append(
            WindowScore(
                window=TimeWindow(float(i), float(i + 1)),
                final_score=value,
                audio_score=value,
                motion_score=0.0,
                scene_signal=0.0,
                reason="moderate activity",
            )
        )
    return scores


def _flat_score_windows(n: int, *, peak_index: int | None = None, peak_value: float = 1.0):
    scores = []
    for i in range(n):
        final = peak_value if i == peak_index else 0.0
        scores.append(
            WindowScore(
                window=TimeWindow(float(i), float(i + 1)),
                final_score=final,
                audio_score=final,
                motion_score=0.0,
                scene_signal=0.0,
                reason="moderate activity",
            )
        )
    return scores


# ---------------------------------------------------------------------------
# generate_candidate_windows
# ---------------------------------------------------------------------------


def test_best_window_covers_the_peak() -> None:
    # 40 one-second bins, a sharp peak at bin 20.
    window_scores = _flat_score_windows(40, peak_index=20, peak_value=10.0)
    config = WindowSelectorConfig(min_clip_seconds=15, max_clip_seconds=20, duration_step_seconds=5)

    candidates = generate_candidate_windows(window_scores, config)

    assert candidates
    best = candidates[0]
    assert best.start_seconds <= 20.0 < best.end_seconds


def test_candidates_respect_duration_constraints() -> None:
    window_scores = _flat_score_windows(60, peak_index=30, peak_value=5.0)
    config = WindowSelectorConfig(min_clip_seconds=10, max_clip_seconds=25, duration_step_seconds=5)

    candidates = generate_candidate_windows(window_scores, config)

    for c in candidates:
        assert 10.0 <= c.duration_seconds <= 25.0


def test_candidates_are_clamped_to_video_boundaries() -> None:
    window_scores = _flat_score_windows(20, peak_index=19, peak_value=5.0)
    config = WindowSelectorConfig(min_clip_seconds=5, max_clip_seconds=15, duration_step_seconds=5)

    candidates = generate_candidate_windows(window_scores, config)

    for c in candidates:
        assert c.start_seconds >= 0.0
        assert c.end_seconds <= 20.0


def test_generate_candidate_windows_empty_input() -> None:
    assert generate_candidate_windows([]) == []


def test_generate_candidate_windows_too_short_video_returns_no_candidates() -> None:
    window_scores = _flat_score_windows(5)  # only 5s of video
    config = WindowSelectorConfig(min_clip_seconds=15, max_clip_seconds=60)

    assert generate_candidate_windows(window_scores, config) == []


def test_generate_candidate_windows_rejects_invalid_duration_config() -> None:
    window_scores = _flat_score_windows(30)
    with pytest.raises(ClipSelectionError):
        generate_candidate_windows(
            window_scores, WindowSelectorConfig(min_clip_seconds=30, max_clip_seconds=10)
        )


# ---------------------------------------------------------------------------
# _interval_iou
# ---------------------------------------------------------------------------


def _candidate(start: float, end: float, score: float = 1.0) -> HighlightCandidate:
    return HighlightCandidate(start, end, score, score, score, score, "moderate activity")


def test_interval_iou_identical_intervals_is_one() -> None:
    a = _candidate(0.0, 20.0)
    assert _interval_iou(a, a) == pytest.approx(1.0)


def test_interval_iou_disjoint_intervals_is_zero() -> None:
    a = _candidate(0.0, 20.0)
    b = _candidate(30.0, 50.0)
    assert _interval_iou(a, b) == 0.0


def test_interval_iou_partial_overlap() -> None:
    a = _candidate(0.0, 20.0)   # duration 20
    b = _candidate(10.0, 30.0)  # duration 20, overlap [10,20) = 10
    # union = 20 + 20 - 10 = 30, intersection = 10 -> IoU = 1/3
    assert _interval_iou(a, b) == pytest.approx(10.0 / 30.0)


# ---------------------------------------------------------------------------
# suppress_overlaps
# ---------------------------------------------------------------------------


def test_suppress_overlaps_removes_duplicates() -> None:
    candidates = [
        _candidate(0.0, 20.0, score=0.9),
        _candidate(2.0, 22.0, score=0.8),  # heavy overlap with the first
        _candidate(50.0, 70.0, score=0.7),  # disjoint
    ]

    selected = suppress_overlaps(candidates, iou_threshold=0.35, top_n=5)

    assert len(selected) == 2
    assert selected[0].start_seconds == 0.0
    assert selected[1].start_seconds == 50.0


def test_suppress_overlaps_respects_top_n() -> None:
    candidates = [
        _candidate(0.0, 20.0, score=0.9),
        _candidate(50.0, 70.0, score=0.8),
        _candidate(100.0, 120.0, score=0.7),
    ]

    selected = suppress_overlaps(candidates, iou_threshold=0.35, top_n=2)

    assert len(selected) == 2


def test_suppress_overlaps_top_n_zero_returns_empty() -> None:
    candidates = [_candidate(0.0, 20.0)]
    assert suppress_overlaps(candidates, iou_threshold=0.35, top_n=0) == []


def test_suppress_overlaps_is_deterministic() -> None:
    candidates = [
        _candidate(0.0, 20.0, score=0.9),
        _candidate(2.0, 22.0, score=0.8),
        _candidate(50.0, 70.0, score=0.7),
    ]

    first = suppress_overlaps(candidates, iou_threshold=0.35, top_n=5)
    second = suppress_overlaps(candidates, iou_threshold=0.35, top_n=5)

    assert first == second


def test_top_n_ordering_is_deterministic_end_to_end() -> None:
    window_scores = _flat_score_windows(90, peak_index=45, peak_value=8.0)
    config = WindowSelectorConfig(min_clip_seconds=15, max_clip_seconds=30, duration_step_seconds=5)

    first = generate_candidate_windows(window_scores, config)
    second = generate_candidate_windows(window_scores, config)

    assert first == second
    scores = [c.score for c in first]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Regression: multiple distinct events must survive to the final top-N.
#
# generate_candidate_windows() used to keep only np.argmax() per duration,
# so nearly every tested duration's single best start clustered around
# whichever one event was strongest, and suppress_overlaps() then had only
# that one region's near-duplicates to choose from - genuinely separate
# highlights elsewhere in the source were silently discarded before overlap
# suppression ever ran. These tests assert multiple separated events all
# survive into the ranked, deduplicated output.
# ---------------------------------------------------------------------------


def _dominant_region(
    candidate: HighlightCandidate, peak_regions: list[tuple[int, int, float]]
) -> int | None:
    """Which peak region a candidate overlaps most, or None if it overlaps none.
    Region width is kept close to the tested clip duration (see tests below),
    so a single real event cannot itself be split into two non-overlapping,
    equally-"valid" candidates - only genuinely separate events can."""
    best_index, best_overlap = None, 0.0
    for index, (start, end, _value) in enumerate(peak_regions):
        overlap = max(0.0, min(candidate.end_seconds, end) - max(candidate.start_seconds, start))
        if overlap > best_overlap:
            best_index, best_overlap = index, overlap
    return best_index


def test_three_distinct_peaks_yield_three_distinct_candidates() -> None:
    # 250 one-second bins; three widely separated 18-second-wide events.
    # Region width (18) is deliberately close to the single tested clip
    # duration (15) so two non-overlapping 15s windows cannot both fit
    # inside one region - only three truly separate events can produce
    # three low-mutual-IoU candidates.
    peak_regions = [(20, 38, 9.0), (100, 118, 8.5), (180, 198, 8.0)]
    window_scores = _multi_peak_score_windows(250, peak_regions)
    config = WindowSelectorConfig(min_clip_seconds=15, max_clip_seconds=15, duration_step_seconds=5)

    ranked = generate_candidate_windows(window_scores, config)
    selected = suppress_overlaps(ranked, iou_threshold=config.overlap_iou_threshold, top_n=3)

    assert len(selected) == 3

    matched_regions = {_dominant_region(c, peak_regions) for c in selected}
    assert matched_regions == {0, 1, 2}

    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            assert _interval_iou(selected[i], selected[j]) <= config.overlap_iou_threshold


def test_five_distinct_peaks_yield_five_distinct_candidates() -> None:
    peak_regions = [
        (10, 28, 9.5),
        (70, 88, 9.0),
        (130, 148, 8.5),
        (190, 208, 8.0),
        (250, 268, 7.5),
    ]
    window_scores = _multi_peak_score_windows(290, peak_regions)
    config = WindowSelectorConfig(min_clip_seconds=15, max_clip_seconds=15, duration_step_seconds=5)

    ranked = generate_candidate_windows(window_scores, config)
    selected = suppress_overlaps(ranked, iou_threshold=config.overlap_iou_threshold, top_n=5)

    assert len(selected) == 5

    matched_regions = {_dominant_region(c, peak_regions) for c in selected}
    assert matched_regions == {0, 1, 2, 3, 4}

    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            assert _interval_iou(selected[i], selected[j]) <= config.overlap_iou_threshold
