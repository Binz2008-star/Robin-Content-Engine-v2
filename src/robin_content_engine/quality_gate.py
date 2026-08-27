from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import imageio_ffmpeg
import numpy as np
from moviepy import VideoFileClip

from .clip_selector import WindowSelectorConfig

_MANIFEST_FORMAT_VERSION = "1"

# Matches the codec/container duration tolerance already used by
# clip_cutter/vertical_reframe/captioner for the same reason: encoders
# round to whole frames, so an exact-second match is not realistic.
_DEFAULT_DURATION_TOLERANCE_SECONDS = 0.5

# 9:16 exactly is 0.5625; a couple of percent of slack absorbs integer
# pixel rounding (e.g. floor-to-even-width cropping in vertical_reframe.py)
# without accepting a genuinely wrong aspect ratio.
_DEFAULT_ASPECT_RATIO_TOLERANCE = 0.02

_DEFAULT_MIN_FPS = 1.0
_DEFAULT_MAX_FPS = 120.0

# Mean 0-255 grayscale luma below this is treated as an effectively
# black/empty frame. Conservative on purpose: normal dark Fortnite
# gameplay (dim interiors, night maps) commonly sits well above this -
# this threshold only catches a genuinely blank/black frame (e.g. an
# encoder glitch or an accidental leading/trailing black pad), not merely
# dark content. Configurable per-call via QualityGateConfig.
_DEFAULT_BLACK_FRAME_LUMA_THRESHOLD = 8.0

_DEFAULT_SAMPLE_FRAME_COUNT = 5

# Upper bound on the full ffmpeg decode-integrity pass. A ~1-minute 1080p
# short decodes in a few seconds even on modest hardware; the bound exists
# only so a hung decode can never block the pipeline forever.
_FFMPEG_DECODE_TIMEOUT_SECONDS = 120

# The minimum delivered resolution for a publishable Short - the standard
# YouTube Shorts size. A clip below this (e.g. a 200x360 crop from a low-
# resolution source that was never upscaled) is far too small to look good
# on YouTube and must never pass the gate or be uploaded.
_DEFAULT_MIN_WIDTH = 1080
_DEFAULT_MIN_HEIGHT = 1920

_ALL_CHECK_NAMES = (
    "file_exists",
    "file_non_empty",
    "video_decodable",
    "decode_integrity_ffmpeg",
    "duration_within_bounds",
    "aspect_ratio_9_16",
    "valid_dimensions",
    "min_resolution",
    "valid_fps",
    "audio_present",
    "no_black_start_frame",
    "no_black_end_frame",
    "sampled_frame_decode_integrity",
    "metadata_no_nan",
)


@dataclass(frozen=True)
class QualityGateConfig:
    """Every threshold used by run_quality_gate(), explicit and overridable -
    none of the pass/fail logic is buried in a magic number inline."""

    min_clip_seconds: float = WindowSelectorConfig().min_clip_seconds
    max_clip_seconds: float = WindowSelectorConfig().max_clip_seconds
    duration_tolerance_seconds: float = _DEFAULT_DURATION_TOLERANCE_SECONDS
    target_aspect_ratio: float = 9 / 16
    aspect_ratio_tolerance: float = _DEFAULT_ASPECT_RATIO_TOLERANCE
    min_fps: float = _DEFAULT_MIN_FPS
    max_fps: float = _DEFAULT_MAX_FPS
    min_width: int = _DEFAULT_MIN_WIDTH
    min_height: int = _DEFAULT_MIN_HEIGHT
    black_frame_luma_threshold: float = _DEFAULT_BLACK_FRAME_LUMA_THRESHOLD
    sample_frame_count: int = _DEFAULT_SAMPLE_FRAME_COUNT


@dataclass(frozen=True)
class QualityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class MediaMetadata:
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool | None


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    checks: list[QualityCheck] = field(default_factory=list)
    media: MediaMetadata = field(
        default_factory=lambda: MediaMetadata(None, None, None, None, None)
    )

    def failed_checks(self) -> list[QualityCheck]:
        return [c for c in self.checks if not c.passed]


def _is_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _mean_luma(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def _ffmpeg_decode_error_count(path: Path) -> int:
    """Fully decode the file with ffmpeg at error verbosity and count
    emitted error lines. This catches corruption the lenient sampling-based
    checks miss - e.g. a TRUNCATED mp4 whose moov atom (faststart) survives
    and whose few sampled frames still decode, but whose stream is actually
    broken mid-file. A healthy file emits zero error lines; anything else
    is a corrupted/partial artifact and must never be published or reused.
    Returns -1 when the decode could not be verified at all (subprocess
    failure or timeout) - treated as a failed check, conservatively."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=_FFMPEG_DECODE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return len([line for line in result.stderr.splitlines() if line.strip()])


def _read_frame_at(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(max(0, frame_index)))
    ok, frame = cap.read()
    return frame if ok else None


def _inspect_frames(
    path: Path, config: QualityGateConfig
) -> tuple[QualityCheck, QualityCheck, QualityCheck]:
    """Opens the produced file once via OpenCV and evaluates the start-frame
    and end-frame black-frame checks plus a sampled-frame decode-integrity
    check across evenly spaced points in the clip. Frame count comes from
    OpenCV's own CAP_PROP_FRAME_COUNT (not a duration*fps estimate from a
    different decoder) so the sampled indices are always in range for the
    same VideoCapture doing the seeking. Never raises - any failure to
    open/read becomes a failed QualityCheck instead."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        detail = "OpenCV could not open the video for frame sampling."
        return (
            QualityCheck("no_black_start_frame", False, detail),
            QualityCheck("no_black_end_frame", False, detail),
            QualityCheck("sampled_frame_decode_integrity", False, detail),
        )

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            detail = "OpenCV could not determine a usable frame count."
            return (
                QualityCheck("no_black_start_frame", False, detail),
                QualityCheck("no_black_end_frame", False, detail),
                QualityCheck("sampled_frame_decode_integrity", False, detail),
            )

        last_index = total_frames - 1
        sample_count = max(2, config.sample_frame_count)
        sample_indices = sorted(
            {
                round(i * last_index / (sample_count - 1))
                for i in range(sample_count)
            }
        )

        start_frame = _read_frame_at(cap, 0)
        end_frame = _read_frame_at(cap, last_index)

        decoded = 0
        for index in sample_indices:
            frame = _read_frame_at(cap, index)
            if frame is not None:
                decoded += 1

        decode_check = QualityCheck(
            "sampled_frame_decode_integrity",
            decoded == len(sample_indices),
            f"decoded {decoded}/{len(sample_indices)} sampled frames "
            f"at indices {sample_indices}",
        )

        if start_frame is None:
            start_check = QualityCheck(
                "no_black_start_frame", False, "Could not decode the first frame."
            )
        else:
            luma = _mean_luma(start_frame)
            start_check = QualityCheck(
                "no_black_start_frame",
                luma >= config.black_frame_luma_threshold,
                f"start-frame mean luma={luma:.2f}, threshold="
                f"{config.black_frame_luma_threshold}",
            )

        if end_frame is None:
            end_check = QualityCheck(
                "no_black_end_frame", False, "Could not decode the last frame."
            )
        else:
            luma = _mean_luma(end_frame)
            end_check = QualityCheck(
                "no_black_end_frame",
                luma >= config.black_frame_luma_threshold,
                f"end-frame mean luma={luma:.2f}, threshold="
                f"{config.black_frame_luma_threshold}",
            )

        return start_check, end_check, decode_check
    finally:
        cap.release()


def run_quality_gate(path: Path, config: QualityGateConfig | None = None) -> QualityGateResult:
    """Inspect one local media artifact and decide PASS or FAIL with an
    explicit reason per check. Every check in _ALL_CHECK_NAMES always
    appears in the result exactly once - a prerequisite failure (file
    missing, empty, or not decodable) marks every dependent check as
    failed with an explicit "skipped" detail rather than omitting it, so
    a caller never has to infer a failure from a check's absence.

    Read-only: never modifies, moves, renames, or deletes the inspected
    file. Does not require a database connection - a local artifact must
    be inspectable even when the queue/rights database is unreachable.
    """
    config = config or QualityGateConfig()
    checks: list[QualityCheck] = []

    def record(name: str, passed: bool, detail: str) -> bool:
        checks.append(QualityCheck(name=name, passed=passed, detail=detail))
        return passed

    def fail_remaining(after: str, detail: str) -> None:
        remaining = _ALL_CHECK_NAMES[_ALL_CHECK_NAMES.index(after) + 1 :]
        for name in remaining:
            record(name, False, detail)

    exists = path.is_file()
    if not record("file_exists", exists, str(path) if exists else f"File does not exist: {path}"):
        fail_remaining("file_exists", "Skipped: file does not exist.")
        return QualityGateResult(passed=False, checks=checks)

    size_bytes = path.stat().st_size
    non_empty = size_bytes > 0
    if not record(
        "file_non_empty",
        non_empty,
        f"{size_bytes} bytes" if non_empty else "File is zero bytes.",
    ):
        fail_remaining("file_non_empty", "Skipped: file is empty.")
        return QualityGateResult(passed=False, checks=checks)

    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool | None = None
    try:
        with VideoFileClip(str(path)) as clip:
            duration = float(clip.duration) if clip.duration else None
            if clip.size:
                width, height = int(clip.size[0]), int(clip.size[1])
            fps = float(clip.fps) if clip.fps else None
            has_audio = clip.audio is not None
    except Exception as exc:
        record("video_decodable", False, f"Failed to open/decode video: {exc}")
        fail_remaining("video_decodable", "Skipped: video could not be decoded.")
        media = MediaMetadata(duration, width, height, fps, has_audio)
        return QualityGateResult(passed=False, checks=checks, media=media)

    record(
        "video_decodable",
        True,
        f"duration={duration}, size={width}x{height}, fps={fps}, has_audio={has_audio}",
    )
    media = MediaMetadata(duration, width, height, fps, has_audio)

    error_count = _ffmpeg_decode_error_count(path)
    if error_count < 0:
        record(
            "decode_integrity_ffmpeg",
            False,
            "Full ffmpeg decode could not be verified (subprocess error or timeout).",
        )
    elif error_count == 0:
        record(
            "decode_integrity_ffmpeg",
            True,
            "Full ffmpeg decode completed with zero errors.",
        )
    else:
        record(
            "decode_integrity_ffmpeg",
            False,
            f"Full ffmpeg decode reported {error_count} error line(s) - corrupted/partial file.",
        )

    if duration is None:
        record("duration_within_bounds", False, "No duration metadata available.")
    else:
        lower = config.min_clip_seconds - config.duration_tolerance_seconds
        upper = config.max_clip_seconds + config.duration_tolerance_seconds
        record(
            "duration_within_bounds",
            lower <= duration <= upper,
            f"duration={duration:.3f}s, expected [{config.min_clip_seconds}, "
            f"{config.max_clip_seconds}]s +/- {config.duration_tolerance_seconds}s",
        )

    if width and height:
        ratio = width / height
        record(
            "aspect_ratio_9_16",
            abs(ratio - config.target_aspect_ratio) <= config.aspect_ratio_tolerance,
            f"{width}x{height} -> ratio={ratio:.4f}, expected "
            f"{config.target_aspect_ratio:.4f} +/- {config.aspect_ratio_tolerance}",
        )
    else:
        record("aspect_ratio_9_16", False, "No dimension metadata available.")

    record(
        "valid_dimensions",
        bool(width and height and width > 0 and height > 0),
        f"{width}x{height}",
    )

    if width and height:
        record(
            "min_resolution",
            width >= config.min_width and height >= config.min_height,
            f"{width}x{height}, required >= {config.min_width}x{config.min_height}",
        )
    else:
        record("min_resolution", False, "No dimension metadata available.")

    if fps is None:
        record("valid_fps", False, "No FPS metadata available.")
    else:
        record(
            "valid_fps",
            _is_finite(fps) and config.min_fps <= fps <= config.max_fps,
            f"fps={fps}, expected [{config.min_fps}, {config.max_fps}]",
        )

    record(
        "audio_present",
        bool(has_audio),
        "Audio stream detected." if has_audio else "No audio stream detected.",
    )

    start_check, end_check, decode_check = _inspect_frames(path, config)
    checks.append(start_check)
    checks.append(end_check)
    checks.append(decode_check)

    metadata_values = [duration, width, height, fps]
    metadata_ok = all(
        value is not None and (not isinstance(value, float) or math.isfinite(value))
        for value in metadata_values
    )
    record(
        "metadata_no_nan",
        metadata_ok,
        "All metadata values present and finite."
        if metadata_ok
        else f"Invalid/missing metadata values: duration={duration}, width={width}, "
        f"height={height}, fps={fps}",
    )

    overall = all(check.passed for check in checks)
    return QualityGateResult(passed=overall, checks=checks, media=media)


class PackagingError(Exception):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PackageResult:
    package_dir: Path
    packaged_video_path: Path
    manifest_path: Path
    manifest: dict[str, Any]


def package_short(
    source_path: Path,
    dest_root: Path,
    *,
    config: QualityGateConfig | None = None,
    now: datetime | None = None,
) -> PackageResult:
    """Run the exact same quality gate against source_path; if any mandatory
    check fails, raise PackagingError listing every failed check and create
    nothing. If it passes, copy source_path (never move, modify, or delete
    it) plus a JSON manifest (no secrets, no OAuth tokens) into a new
    dest_root/<source stem>/ directory. Fails safely - raises and creates
    nothing new - if that destination directory already exists, rather than
    silently overwriting a prior package. Never uploads anything.
    """
    result = run_quality_gate(source_path, config)
    if not result.passed:
        reasons = "; ".join(f"{c.name}: {c.detail}" for c in result.failed_checks())
        raise PackagingError(
            f"Quality gate FAILED for {source_path}, refusing to package. {reasons}"
        )

    package_dir = dest_root / source_path.stem
    if package_dir.exists():
        raise PackagingError(
            f"Package destination already exists, refusing to overwrite: {package_dir}"
        )

    package_dir.parent.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir()

    packaged_video_path = package_dir / source_path.name
    shutil.copy2(source_path, packaged_video_path)

    sha256 = _sha256_file(packaged_video_path)
    timestamp = (now or datetime.now(UTC)).isoformat()

    manifest: dict[str, Any] = {
        "format_version": _MANIFEST_FORMAT_VERSION,
        "original_artifact_path": str(source_path),
        "packaged_artifact_path": str(packaged_video_path),
        "sha256": sha256,
        "byte_size": packaged_video_path.stat().st_size,
        "duration_seconds": result.media.duration_seconds,
        "width": result.media.width,
        "height": result.media.height,
        "fps": result.media.fps,
        "audio_present": result.media.has_audio,
        "quality_gate_passed": result.passed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks
        ],
        "packaged_at": timestamp,
    }

    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return PackageResult(
        package_dir=package_dir,
        packaged_video_path=packaged_video_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )
