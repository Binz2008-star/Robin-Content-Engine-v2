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
    _containment_ratio,
    _interval_iou,
    generate_candidate_windows,
    suppress_overlaps,
)
from robin_content_engine.highlight_features import (  # noqa: E402
    TimeWindow,
    generate_time_windows,
)
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


# ---------------------------------------------------------------------------
# Regression: non-integral source duration must not silently violate the
# real-time min/max clip duration contract.
#
# generate_time_windows() truncates the final bin when the source duration
# isn't an exact multiple of the grid width (e.g. a 26.555s source at a
# 1.0s grid ends with a 0.555s final bin, not a full 1.0s one).
# generate_candidate_windows() converted min/max_clip_seconds to a bin
# COUNT using the first window's width as the nominal bin size, so a
# candidate spanning the configured bin count could span LESS real time
# than min_clip_seconds if it included that truncated final bin. This
# reproduces the exact real-smoke boundary case (26.555s source,
# min_clip_seconds=15.0, tail activity) that used to return a 14.555s
# candidate starting at 12.0s and ending at 26.555s.
# ---------------------------------------------------------------------------


def test_non_integral_final_bin_does_not_produce_undersized_candidate() -> None:
    windows = generate_time_windows(26.555, 1.0)
    assert windows[-1] == TimeWindow(26.0, 26.555)  # exact real-smoke source duration

    # Activity concentrated in the tail, including the truncated final bin -
    # this is exactly the profile that previously produced the defective
    # 12.0s-26.555s (14.555s) candidate.
    window_scores = [
        WindowScore(
            window=w,
            final_score=1.0 if i >= 12 else 0.0,
            audio_score=1.0 if i >= 12 else 0.0,
            motion_score=0.0,
            scene_signal=0.0,
            reason="moderate activity",
        )
        for i, w in enumerate(windows)
    ]
    config = WindowSelectorConfig()  # min_clip_seconds=15.0 default

    candidates = generate_candidate_windows(window_scores, config)

    assert candidates, "expected at least one valid candidate"
    for c in candidates:
        assert c.duration_seconds >= config.min_clip_seconds - 1e-6, c
    # The specific defective candidate must never appear.
    assert not any(
        c.start_seconds == 12.0 and c.end_seconds == 26.555 for c in candidates
    )
    # The real fix: the true best 15s-real-duration window is found instead.
    assert candidates[0].start_seconds == 11.0
    assert candidates[0].end_seconds == 26.0
    assert candidates[0].duration_seconds == pytest.approx(15.0)


def test_all_candidates_respect_real_time_bounds_on_non_integral_duration() -> None:
    windows = generate_time_windows(26.555, 1.0)
    window_scores = [
        WindowScore(
            window=w,
            final_score=float((i * 7) % 5),  # varied, deterministic, non-trivial profile
            audio_score=float((i * 7) % 5),
            motion_score=float((i * 3) % 4),
            scene_signal=0.0,
            reason="moderate activity",
        )
        for i, w in enumerate(windows)
    ]
    config = WindowSelectorConfig(
        min_clip_seconds=15.0, max_clip_seconds=25.0, duration_step_seconds=5.0
    )

    candidates = generate_candidate_windows(window_scores, config)

    assert candidates
    lower = config.min_clip_seconds - 1e-6
    upper = config.max_clip_seconds + 1e-6
    for c in candidates:
        assert lower <= c.duration_seconds <= upper


# ---------------------------------------------------------------------------
# Regression: the global candidate pool must never be truncated before
# suppress_overlaps() runs.
#
# generate_candidate_windows() used to sort the full pool and return only
# `candidates[:max_candidates_before_dedup]` (default 50). On a long source,
# the highest-scoring ~50 raw candidates can all be overlapping/diluted
# variants of a single dominant event (many tested durations x many start
# offsets all partially covering the same active region) - a real ~409s
# Fortnite capture (job 19) reproduced exactly this: requesting --top 5
# returned only 2 near-duplicate candidates, both in the source's final
# ~30 seconds, because every other genuinely distinct (but lower-scoring)
# event never made it into the top-50 pool suppress_overlaps() was ever
# shown. The fix removes the cap entirely - the full globally-ranked pool
# is what gets passed to suppress_overlaps(), which already stops as soon
# as top_n distinct candidates are accepted.
# ---------------------------------------------------------------------------


def test_pre_dedup_truncation_no_longer_discards_distinct_earlier_events() -> None:
    # ~409s source (matches the real job-19 capture length), one dominant
    # late event and four widely-separated earlier events. Event width is
    # kept exactly at min_clip_seconds (15) so each event's own candidates
    # cleanly collapse to a single survivor under suppress_overlaps (a wider
    # plateau can itself yield two low-mutual-IoU variants of the SAME
    # event - a separate, real characteristic of temporal IoU suppression,
    # not what this correction is about). A dense duration_step_seconds=1.0
    # makes the dominant event alone generate far more than 50 raw
    # candidates across all tested durations - enough that the OLD
    # cap-then-suppress behavior (simulated below) starves every earlier
    # event entirely, which is exactly the defect being fixed.
    duration_seconds = 409.055
    windows = generate_time_windows(duration_seconds, 1.0)
    n = len(windows)
    regions = [
        (30, 45, 5.0),
        (120, 135, 5.0),
        (210, 225, 5.0),
        (300, 315, 5.0),
        (n - 35, n - 20, 10.0),  # dominant, near the end - matches job 19
    ]

    def value_at(i: int) -> float:
        for start, end, value in regions:
            if start <= i < end:
                return value
        return 0.0

    window_scores = [
        WindowScore(w, value_at(i), value_at(i), 0.0, 0.0, "moderate activity")
        for i, w in enumerate(windows)
    ]
    config = WindowSelectorConfig(duration_step_seconds=1.0)

    ranked = generate_candidate_windows(window_scores, config)

    # The corrected function must not have truncated the pool itself.
    assert len(ranked) > 50

    # Prove this fixture actually exercises the old defect: simulating the
    # old cap-then-suppress behavior on the SAME ranked pool must fail to
    # find all 5 distinct events (the earlier ones never survive the cut).
    old_style_capped_pool = ranked[:50]
    old_style_selected = suppress_overlaps(
        old_style_capped_pool, iou_threshold=config.overlap_iou_threshold, top_n=5
    )
    assert len(old_style_selected) < 5, (
        "fixture does not reproduce the pre-dedup truncation defect - "
        "the old cap=50 behavior should have starved the earlier events"
    )

    # The actual fix: the full, uncapped pool correctly yields all 5.
    selected = suppress_overlaps(ranked, iou_threshold=config.overlap_iou_threshold, top_n=5)

    assert len(selected) == 5

    matched_regions = {_dominant_region(c, regions) for c in selected}
    assert matched_regions == {0, 1, 2, 3, 4}

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


# ---------------------------------------------------------------------------
# Regression: near-duplicate containment-ratio criterion.
#
# suppress_overlaps() previously rejected duplicates using temporal IoU
# alone. A real job-19 case slipped through: 389-404s (15s) and 378-398s
# (20s) have IoU ~= 0.346 - just under the 0.35 threshold - purely because
# IoU's denominator (the union) grows with the longer candidate. But 9 of
# the shorter clip's 15 seconds (60%) are duplicated inside the longer one.
# suppress_overlaps() now also rejects a candidate if
# intersection / min(duration_a, duration_b) >= containment_threshold
# (default 0.50), independent of IoU.
# ---------------------------------------------------------------------------


def _containment_test_candidate(start: float, end: float, score: float = 1.0) -> HighlightCandidate:
    return HighlightCandidate(start, end, score, score, score, 0.0, "moderate activity")


def test_containment_ratio_matches_real_job19_case() -> None:
    a = _containment_test_candidate(389.0, 404.0)  # 15s
    b = _containment_test_candidate(378.0, 398.0)  # 20s

    assert _interval_iou(a, b) == pytest.approx(9.0 / 26.0)  # ~0.346, under 0.35
    assert _containment_ratio(a, b) == pytest.approx(0.60)  # 9 / 15


def test_exact_job19_duplicate_is_rejected() -> None:
    # Higher-scored candidate first, as suppress_overlaps expects pre-sorted input.
    higher = _containment_test_candidate(389.0, 404.0, score=1.0)
    lower = _containment_test_candidate(378.0, 398.0, score=0.9)

    selected = suppress_overlaps([higher, lower], iou_threshold=0.35, top_n=5)

    assert len(selected) == 1
    assert selected[0] is higher


def test_genuinely_adjacent_low_overlap_candidates_both_kept() -> None:
    # Two real, separate events with only a small, incidental overlap -
    # must NOT be treated as duplicates by either criterion.
    first = _containment_test_candidate(100.0, 120.0, score=1.0)  # 20s
    second = _containment_test_candidate(115.0, 135.0, score=0.9)  # 20s, overlap=[115,120)=5s

    assert _interval_iou(first, second) == pytest.approx(5.0 / 35.0)  # ~0.143
    assert _containment_ratio(first, second) == pytest.approx(5.0 / 20.0)  # 0.25

    selected = suppress_overlaps([first, second], iou_threshold=0.35, top_n=5)

    assert len(selected) == 2
    assert {c.start_seconds for c in selected} == {100.0, 115.0}


def test_containment_threshold_is_configurable_and_not_hidden() -> None:
    # Must use a pair where IoU alone would NOT reject it (otherwise raising
    # containment_threshold can't actually be observed to change anything -
    # a prior version of this test made exactly that mistake, using a pair
    # with IoU=0.60 that IoU rejected regardless of containment_threshold).
    # The real job-19 case is exactly such a pair: IoU ~= 0.346, under the
    # 0.35 IoU threshold, so only the containment criterion is in play.
    config = WindowSelectorConfig()
    assert config.containment_threshold == pytest.approx(0.50)

    higher = _containment_test_candidate(389.0, 404.0, score=1.0)  # 15s
    lower = _containment_test_candidate(378.0, 398.0, score=0.9)  # 20s

    assert _interval_iou(higher, lower) < 0.35  # IoU alone would keep both
    assert _containment_ratio(higher, lower) == pytest.approx(0.60)

    # Default threshold (0.50): 0.60 >= 0.50 -> rejected as a duplicate.
    default_selected = suppress_overlaps([higher, lower], iou_threshold=0.35, top_n=5)
    assert len(default_selected) == 1

    # Raised threshold (0.70): 0.60 < 0.70 -> containment no longer
    # triggers, and IoU (~=0.346) still doesn't either, so both are kept.
    # This is the actual proof that containment_threshold changes behavior.
    permissive_selected = suppress_overlaps(
        [higher, lower], iou_threshold=0.35, top_n=5, containment_threshold=0.70
    )
    assert len(permissive_selected) == 2


def test_containment_ratio_symmetric_and_bounded() -> None:
    a = _containment_test_candidate(0.0, 10.0)
    b = _containment_test_candidate(2.0, 8.0)  # fully inside a

    ratio_ab = _containment_ratio(a, b)
    ratio_ba = _containment_ratio(b, a)

    assert ratio_ab == pytest.approx(1.0)  # all of b (the shorter) is inside a
    assert ratio_ba == pytest.approx(1.0)  # symmetric: same intersection / same shorter duration
    assert 0.0 <= ratio_ab <= 1.0
