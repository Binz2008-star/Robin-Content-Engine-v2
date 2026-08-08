from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from moviepy import AudioFileClip

from .scene_detector import SceneBoundary


class FeatureExtractionError(Exception):
    pass


@dataclass(frozen=True)
class TimeWindow:
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class AudioFeatureConfig:
    """window_seconds must match the grid used to build `windows` elsewhere."""

    sample_rate: int = 16000
    fft_frame_size: int = 512
    fft_hop_size: int = 256


@dataclass(frozen=True)
class MotionFeatureConfig:
    sample_fps: float = 2.0
    downscale_width: int = 160


def generate_time_windows(duration_seconds: float, window_seconds: float) -> list[TimeWindow]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    windows: list[TimeWindow] = []
    start = 0.0
    while start < duration_seconds:
        end = min(start + window_seconds, duration_seconds)
        windows.append(TimeWindow(start, end))
        start = end
    return windows


def compute_audio_window_features(
    samples: np.ndarray,
    frame_size: int = 512,
    hop_size: int = 256,
) -> tuple[float, float]:
    """Pure function: RMS energy and spectral flux for one window of audio.

    `samples` is a 1-D (mono) or 2-D (n_samples, n_channels) array. Returns
    (rms, spectral_flux) as non-negative finite floats; (0.0, 0.0) for
    empty or too-short input rather than raising, since a window landing
    at end-of-file is an expected, not exceptional, case.
    """
    if samples.size == 0:
        return 0.0, 0.0

    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    mono = mono.astype(np.float64)

    rms = float(np.sqrt(np.mean(np.square(mono))))

    if mono.shape[0] < frame_size:
        return rms, 0.0

    hann = np.hanning(frame_size)
    n_frames = 1 + (mono.shape[0] - frame_size) // hop_size
    if n_frames < 2:
        return rms, 0.0

    prev_mag: np.ndarray | None = None
    flux_values: list[float] = []
    for i in range(n_frames):
        start = i * hop_size
        frame = mono[start : start + frame_size] * hann
        mag = np.abs(np.fft.rfft(frame))
        if prev_mag is not None:
            diff = mag - prev_mag
            flux_values.append(float(np.sum(diff[diff > 0])))
        prev_mag = mag

    spectral_flux = float(np.mean(flux_values)) if flux_values else 0.0
    return rms, spectral_flux


def extract_audio_activity(
    video_path: Path,
    windows: Sequence[TimeWindow],
    config: AudioFeatureConfig | None = None,
) -> tuple[list[float], list[float]]:
    """Streams audio window-by-window via moviepy (ffmpeg-backed) rather than
    decoding the full track into memory at once. Returns (raw_rms, raw_flux),
    aligned index-for-index with `windows`, both un-normalized.
    """
    config = config or AudioFeatureConfig()
    if not windows:
        return [], []

    try:
        audio = AudioFileClip(str(video_path))
    except Exception as exc:
        raise FeatureExtractionError(f"Could not open audio for {video_path}: {exc}") from exc

    rms_values: list[float] = []
    flux_values: list[float] = []
    try:
        for w in windows:
            try:
                clip = audio.subclipped(w.start_seconds, w.end_seconds)
                samples = clip.to_soundarray(fps=config.sample_rate)
            except Exception:
                # A window landing exactly at end-of-file can fail to decode;
                # treat it as silence rather than aborting the whole scan.
                samples = np.zeros((0,), dtype=np.float64)
            rms, flux = compute_audio_window_features(
                samples, config.fft_frame_size, config.fft_hop_size
            )
            rms_values.append(rms)
            flux_values.append(flux)
    finally:
        audio.close()

    return rms_values, flux_values


def compute_frame_motion(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Pure function: mean absolute pixel difference between two same-shaped
    single-channel frames, in [0, 255]."""
    if prev_gray.shape != curr_gray.shape:
        raise ValueError("Frames must have matching shape")
    diff = cv2.absdiff(curr_gray, prev_gray)
    return float(np.mean(diff))


def _downscale_gray(frame: np.ndarray, target_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > target_width > 0:
        scale = target_width / width
        frame = cv2.resize(
            frame,
            (target_width, max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def extract_motion_activity(
    video_path: Path,
    windows: Sequence[TimeWindow],
    config: MotionFeatureConfig | None = None,
) -> list[float]:
    """Samples frames at `config.sample_fps` (never every full-resolution
    frame) and downscales before diffing. One seek per window to its start,
    then strictly sequential reads within the window - repeated mid-window
    seeking is avoided since OpenCV/ffmpeg seek accuracy on compressed
    codecs is not frame-exact, which would make sampling non-deterministic.
    """
    config = config or MotionFeatureConfig()
    if not windows:
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FeatureExtractionError(f"Could not open video for motion analysis: {video_path}")

    try:
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if source_fps <= 0:
            raise FeatureExtractionError(f"Could not determine frame rate for {video_path}")

        sample_fps = min(config.sample_fps, source_fps) if config.sample_fps > 0 else source_fps
        frame_interval = max(1, round(source_fps / sample_fps))

        motion_values: list[float] = []
        for w in windows:
            start_frame = int(w.start_seconds * source_fps)
            end_frame = int(w.end_seconds * source_fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            prev_gray: np.ndarray | None = None
            diffs: list[float] = []
            offset = 0
            frame_idx = start_frame
            while frame_idx < end_frame:
                ok, frame = cap.read()
                if not ok:
                    break
                if offset % frame_interval == 0:
                    gray = _downscale_gray(frame, config.downscale_width)
                    if prev_gray is not None:
                        diffs.append(compute_frame_motion(prev_gray, gray))
                    prev_gray = gray
                offset += 1
                frame_idx += 1

            motion_values.append(float(np.mean(diffs)) if diffs else 0.0)

        return motion_values
    finally:
        cap.release()


def compute_scene_density(
    scenes: Sequence[SceneBoundary],
    windows: Sequence[TimeWindow],
) -> list[float]:
    """Pure function: raw count of scene-cut starts falling inside each
    window. The first scene's own start (0.0) is not itself a cut."""
    cut_starts = [s.start_seconds for s in scenes[1:]]
    return [
        float(sum(1 for t in cut_starts if w.start_seconds <= t < w.end_seconds))
        for w in windows
    ]


def normalize_signal(values: Sequence[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Empty or constant input maps to all
    zeros rather than NaN/inf - a flat signal (e.g. total silence) should
    score low, not undefined."""
    if not values:
        return []
    arr = np.asarray(values, dtype=np.float64)
    lo, hi = float(arr.min()), float(arr.max())
    spread = hi - lo
    if spread <= 1e-12:
        return [0.0] * len(values)
    normalized = np.clip((arr - lo) / spread, 0.0, 1.0)
    return [float(v) for v in normalized]
