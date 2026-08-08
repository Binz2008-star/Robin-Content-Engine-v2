from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from robin_content_engine.highlight_features import (  # noqa: E402
    MotionFeatureConfig,
    TimeWindow,
    compute_audio_window_features,
    compute_frame_motion,
    compute_scene_density,
    extract_motion_activity,
    generate_time_windows,
    normalize_signal,
)
from robin_content_engine.scene_detector import SceneBoundary  # noqa: E402

# ---------------------------------------------------------------------------
# generate_time_windows
# ---------------------------------------------------------------------------


def test_generate_time_windows_tiles_the_full_duration() -> None:
    windows = generate_time_windows(duration_seconds=3.5, window_seconds=1.0)

    assert [w.start_seconds for w in windows] == [0.0, 1.0, 2.0, 3.0]
    assert windows[-1].end_seconds == 3.5  # last window truncated, not overrun
    assert windows[0].start_seconds == 0.0


def test_generate_time_windows_rejects_non_positive_inputs() -> None:
    with pytest.raises(ValueError, match="duration_seconds"):
        generate_time_windows(duration_seconds=0.0, window_seconds=1.0)
    with pytest.raises(ValueError, match="window_seconds"):
        generate_time_windows(duration_seconds=5.0, window_seconds=0.0)


# ---------------------------------------------------------------------------
# compute_audio_window_features (pure)
# ---------------------------------------------------------------------------


def test_audio_features_silence_scores_low() -> None:
    silence = np.zeros(16000, dtype=np.float64)
    rms, flux = compute_audio_window_features(silence)

    assert rms == 0.0
    assert flux == 0.0


def test_audio_features_synthetic_spike_scores_higher_than_silence() -> None:
    silence = np.zeros(16000, dtype=np.float64)
    t = np.linspace(0, 1.0, 16000, endpoint=False)
    tone = 0.8 * np.sin(2 * np.pi * 440 * t)

    silence_rms, _ = compute_audio_window_features(silence)
    tone_rms, _ = compute_audio_window_features(tone)

    assert tone_rms > silence_rms
    assert tone_rms > 0


def test_audio_features_handles_stereo_input() -> None:
    t = np.linspace(0, 1.0, 16000, endpoint=False)
    mono_tone = 0.8 * np.sin(2 * np.pi * 440 * t)
    stereo_tone = np.stack([mono_tone, mono_tone], axis=1)

    mono_rms, _ = compute_audio_window_features(mono_tone)
    stereo_rms, _ = compute_audio_window_features(stereo_tone)

    assert stereo_rms == pytest.approx(mono_rms, rel=1e-6)


def test_audio_features_empty_input_is_safe() -> None:
    rms, flux = compute_audio_window_features(np.zeros((0,), dtype=np.float64))
    assert (rms, flux) == (0.0, 0.0)


def test_audio_features_short_input_is_safe() -> None:
    # Shorter than the FFT frame size - RMS still computed, flux safely 0.
    tiny = np.full(10, 0.5, dtype=np.float64)
    rms, flux = compute_audio_window_features(tiny, frame_size=512, hop_size=256)
    assert rms == pytest.approx(0.5)
    assert flux == 0.0


def test_audio_features_output_is_bounded_and_finite() -> None:
    rng = np.random.default_rng(0)
    loud = rng.uniform(-1.0, 1.0, size=16000)
    rms, flux = compute_audio_window_features(loud)
    assert np.isfinite(rms)
    assert np.isfinite(flux)
    assert rms >= 0.0
    assert flux >= 0.0


# ---------------------------------------------------------------------------
# compute_frame_motion (pure)
# ---------------------------------------------------------------------------


def test_motion_identical_frames_scores_zero() -> None:
    frame = np.full((32, 32), 100, dtype=np.uint8)
    assert compute_frame_motion(frame, frame) == 0.0


def test_motion_different_frames_scores_higher() -> None:
    dark = np.full((32, 32), 20, dtype=np.uint8)
    bright = np.full((32, 32), 220, dtype=np.uint8)
    assert compute_frame_motion(dark, bright) > 0.0
    assert compute_frame_motion(dark, dark) < compute_frame_motion(dark, bright)


def test_motion_rejects_mismatched_shapes() -> None:
    a = np.zeros((32, 32), dtype=np.uint8)
    b = np.zeros((16, 16), dtype=np.uint8)
    with pytest.raises(ValueError, match="matching shape"):
        compute_frame_motion(a, b)


# ---------------------------------------------------------------------------
# compute_scene_density (pure)
# ---------------------------------------------------------------------------


def test_scene_density_counts_cuts_per_window() -> None:
    scenes = [
        SceneBoundary(0.0, 1.5, 0, 15),
        SceneBoundary(1.5, 3.2, 15, 32),
        SceneBoundary(3.2, 5.0, 32, 50),
    ]
    windows = [
        TimeWindow(0.0, 1.0),
        TimeWindow(1.0, 2.0),
        TimeWindow(2.0, 3.0),
        TimeWindow(3.0, 4.0),
    ]

    density = compute_scene_density(scenes, windows)

    # Cuts at 1.5 (falls in window [1,2)) and 3.2 (falls in window [3,4)).
    assert density == [0.0, 1.0, 0.0, 1.0]


def test_scene_density_zero_when_no_windows() -> None:
    scenes = [SceneBoundary(0.0, 5.0, 0, 50)]
    assert compute_scene_density(scenes, []) == []


# ---------------------------------------------------------------------------
# normalize_signal (pure)
# ---------------------------------------------------------------------------


def test_normalize_signal_bounded_and_finite() -> None:
    values = [0.0, 5.0, 2.5, 10.0, 1.0]
    normalized = normalize_signal(values)
    assert all(0.0 <= v <= 1.0 for v in normalized)
    assert all(np.isfinite(v) for v in normalized)
    assert normalized[values.index(0.0)] == 0.0
    assert normalized[values.index(10.0)] == 1.0


def test_normalize_signal_constant_input_is_all_zero_not_nan() -> None:
    normalized = normalize_signal([3.0, 3.0, 3.0])
    assert normalized == [0.0, 0.0, 0.0]


def test_normalize_signal_empty_input() -> None:
    assert normalize_signal([]) == []


# ---------------------------------------------------------------------------
# extract_motion_activity (I/O, real synthetic clip)
# ---------------------------------------------------------------------------


def _write_still_then_moving_video(path: Path, *, fps: int = 10, seconds_each: int = 2) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    width, height = 64, 64
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    still = np.full((height, width, 3), 128, dtype=np.uint8)
    for _ in range(fps * seconds_each):
        writer.write(still)
    rng = np.random.default_rng(1)
    for _ in range(fps * seconds_each):
        writer.write(rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8))
    writer.release()


@pytest.fixture
def still_then_moving_video(tmp_path: Path) -> Path:
    video_path = tmp_path / "motion.mp4"
    _write_still_then_moving_video(video_path)
    return video_path


def test_extract_motion_activity_still_segment_scores_lower(still_then_moving_video: Path) -> None:
    windows = [TimeWindow(0.0, 2.0), TimeWindow(2.0, 4.0)]
    values = extract_motion_activity(still_then_moving_video, windows)

    assert len(values) == 2
    assert values[0] < values[1]  # still segment scores lower than the moving segment


def test_extract_motion_activity_is_deterministic(still_then_moving_video: Path) -> None:
    windows = [TimeWindow(0.0, 2.0), TimeWindow(2.0, 4.0)]
    config = MotionFeatureConfig(sample_fps=2.0, downscale_width=32)

    first_run = extract_motion_activity(still_then_moving_video, windows, config)
    second_run = extract_motion_activity(still_then_moving_video, windows, config)

    assert first_run == second_run
