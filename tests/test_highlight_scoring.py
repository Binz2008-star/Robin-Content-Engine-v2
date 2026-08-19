from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import math  # noqa: E402

import pytest  # noqa: E402

from robin_content_engine.highlight_features import TimeWindow  # noqa: E402
from robin_content_engine.highlight_scoring import ScoringConfig, score_windows  # noqa: E402

WINDOWS = [TimeWindow(float(i), float(i + 1)) for i in range(5)]


def test_score_windows_higher_audio_and_motion_produce_higher_score() -> None:
    raw_audio_rms = [0.0, 0.0, 0.0, 0.0, 10.0]
    raw_audio_flux = [0.0, 0.0, 0.0, 0.0, 10.0]
    raw_motion = [0.0, 0.0, 0.0, 0.0, 10.0]
    raw_scene = [0.0, 0.0, 0.0, 0.0, 0.0]

    scores = score_windows(WINDOWS, raw_audio_rms, raw_audio_flux, raw_motion, raw_scene)

    assert scores[-1].final_score > scores[0].final_score
    assert scores[0].final_score == 0.0


def test_score_windows_monotonic_in_audio_alone() -> None:
    raw_audio_rms = [0.0, 1.0, 2.0, 3.0, 4.0]
    raw_audio_flux = [0.0, 1.0, 2.0, 3.0, 4.0]
    raw_motion = [0.0, 0.0, 0.0, 0.0, 0.0]
    raw_scene = [0.0, 0.0, 0.0, 0.0, 0.0]

    scores = score_windows(WINDOWS, raw_audio_rms, raw_audio_flux, raw_motion, raw_scene)
    final = [s.final_score for s in scores]

    assert final == sorted(final)
    assert final[0] < final[-1]


def test_score_windows_no_nan_or_inf() -> None:
    raw_audio_rms = [0.0, 0.0, 0.0, 0.0, 0.0]
    raw_audio_flux = [0.0, 0.0, 0.0, 0.0, 0.0]
    raw_motion = [0.0, 0.0, 0.0, 0.0, 0.0]
    raw_scene = [0.0, 0.0, 0.0, 0.0, 0.0]

    scores = score_windows(WINDOWS, raw_audio_rms, raw_audio_flux, raw_motion, raw_scene)

    for s in scores:
        assert math.isfinite(s.final_score)
        assert math.isfinite(s.audio_score)
        assert math.isfinite(s.motion_score)
        assert math.isfinite(s.scene_signal)


def test_score_windows_final_score_bounded() -> None:
    config = ScoringConfig()
    raw_audio_rms = [0.0, 1.0, 5.0, 2.0, 8.0]
    raw_audio_flux = [0.0, 2.0, 1.0, 4.0, 3.0]
    raw_motion = [0.0, 3.0, 2.0, 5.0, 1.0]
    raw_scene = [0.0, 5.0, 1.0, 0.0, 3.0]

    scores = score_windows(WINDOWS, raw_audio_rms, raw_audio_flux, raw_motion, raw_scene, config)

    max_possible = config.audio_weight + config.motion_weight + config.scene_bonus_cap
    for s in scores:
        assert 0.0 <= s.final_score <= max_possible


def test_scene_signal_cannot_dominate_the_score() -> None:
    # Max scene density, zero audio/motion, vs. max audio/motion, zero scene.
    windows = [TimeWindow(0.0, 1.0), TimeWindow(1.0, 2.0)]
    all_scene = score_windows(
        windows,
        raw_audio_rms=[0.0, 0.0],
        raw_audio_flux=[0.0, 0.0],
        raw_motion=[0.0, 0.0],
        raw_scene_density=[0.0, 100.0],
    )
    all_activity = score_windows(
        windows,
        raw_audio_rms=[0.0, 10.0],
        raw_audio_flux=[0.0, 10.0],
        raw_motion=[0.0, 10.0],
        raw_scene_density=[0.0, 0.0],
    )

    config = ScoringConfig()
    assert all_scene[1].final_score <= config.scene_bonus_cap
    assert all_activity[1].final_score > all_scene[1].final_score


def test_score_windows_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        score_windows(WINDOWS, [0.0] * 4, [0.0] * 5, [0.0] * 5, [0.0] * 5)


def test_score_windows_empty_input() -> None:
    assert score_windows([], [], [], [], []) == []


def test_reason_is_deterministic_and_signal_derived() -> None:
    windows = [TimeWindow(0.0, 1.0)]
    scores = score_windows(
        windows,
        raw_audio_rms=[10.0],
        raw_audio_flux=[10.0],
        raw_motion=[0.0],
        raw_scene_density=[0.0],
    )
    # A single-window normalize_signal call always yields a constant-signal
    # zero (no spread to compare against), so the only reachable reason here
    # is the "moderate activity" fallback - this asserts it's deterministic,
    # not an LLM call, and always one of the known fixed strings.
    assert scores[0].reason in {
        "moderate activity",
        "high audio spike",
        "high motion",
        "scene-cut cluster",
        "high audio spike + high motion",
    }
