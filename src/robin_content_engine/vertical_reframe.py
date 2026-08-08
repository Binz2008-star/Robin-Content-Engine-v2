from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moviepy import VideoFileClip

# width / height for a 9:16 vertical short.
TARGET_ASPECT_RATIO = 9 / 16

# Used both to guard against negligible floating-point accumulation when
# checking a requested end against the source's real duration, and as the
# explicit codec/container tolerance for validating the produced output's
# actual duration against the requested interval.
_DURATION_TOLERANCE_SECONDS = 0.5


class VerticalReframeError(Exception):
    pass


def _probe_output(path: Path) -> tuple[float, int, int]:
    with VideoFileClip(str(path)) as probe:
        width, height = probe.size
        return float(probe.duration), int(width), int(height)


@dataclass(frozen=True)
class ReframeResult:
    output_path: Path
    start_seconds: float
    end_seconds: float
    crop_width: int
    crop_height: int
    crop_x1: int

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def reframe_to_vertical(
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
    *,
    horizontal_offset_ratio: float = 0.5,
) -> ReframeResult:
    """Extract [start_seconds, end_seconds) from source_path and crop it to a
    static, deterministic 9:16 vertical frame - the full source height and a
    9:16-proportioned width taken directly from the source's own frame (no
    resize, no letterbox/pad, no dynamic/subject tracking) - writing a new
    local MP4 (H.264 video, AAC audio) at output_path.

    horizontal_offset_ratio (0.0 = crop aligned to the left edge, 0.5 =
    centered, 1.0 = aligned to the right edge) is a single fixed crop
    position applied to the whole clip - this MVP intentionally has no
    per-frame or subject-aware tracking.

    Never modifies, moves, renames, or deletes source_path. Never overwrites
    an existing output_path - fails instead, so a caller must choose a
    different (e.g. deterministically suffixed) path rather than silently
    clobbering a prior reframe.

    After encoding, the produced file's actual duration and frame dimensions
    are probed and checked against what was requested, within
    _DURATION_TOLERANCE_SECONDS for duration and exactly for dimensions. A
    file that exists and is non-empty but has the wrong duration or the
    wrong crop dimensions is not a success: it is deleted (only the output
    this attempt just created - the source is never touched) and
    VerticalReframeError is raised, so the deterministic output filename
    remains free for a retry.
    """
    if end_seconds <= start_seconds:
        raise VerticalReframeError("end_seconds must be greater than start_seconds")
    if not 0.0 <= horizontal_offset_ratio <= 1.0:
        raise VerticalReframeError("horizontal_offset_ratio must be between 0.0 and 1.0")
    if not source_path.is_file():
        raise VerticalReframeError(f"Source file does not exist: {source_path}")
    if output_path.exists():
        raise VerticalReframeError(
            f"Output file already exists, refusing to overwrite: {output_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(source_path))
    clip = None
    cropped = None
    try:
        if not source.duration or source.duration <= 0:
            raise VerticalReframeError(f"Source video has no usable duration: {source_path}")
        if end_seconds > source.duration + _DURATION_TOLERANCE_SECONDS:
            raise VerticalReframeError(
                f"Requested end_seconds {end_seconds} exceeds source duration "
                f"{source.duration} for {source_path}"
            )

        source_width, source_height = source.size
        # Floor to the nearest even width: libx264's yuv420p pixel format
        # requires even dimensions, and an odd crop width would otherwise
        # make ffmpeg encoding fail.
        crop_width = int(source_height * TARGET_ASPECT_RATIO)
        if crop_width % 2:
            crop_width -= 1
        if crop_width <= 0 or crop_width > source_width:
            raise VerticalReframeError(
                f"Source frame {source_width}x{source_height} is not wide enough for a "
                f"9:16 crop (would need width >= {crop_width})."
            )

        max_x1 = source_width - crop_width
        x1 = round(horizontal_offset_ratio * max_x1)

        clip = source.subclipped(start_seconds, min(end_seconds, source.duration))
        cropped = clip.cropped(x1=x1, y1=0, x2=x1 + crop_width, y2=source_height)
        # fps intentionally omitted: moviepy's @use_clip_fps_by_default falls
        # back to the clip's own native fps (i.e. the source's), preserving
        # it rather than resampling to an arbitrary value.
        cropped.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            pixel_format="yuv420p",
            ffmpeg_params=["-movflags", "+faststart"],
            logger=None,
        )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise VerticalReframeError(
                f"Vertical reframe completed without producing output: {output_path}"
            )

        expected_duration = min(end_seconds, source.duration) - start_seconds
        produced_duration, produced_width, produced_height = _probe_output(output_path)
        if abs(produced_duration - expected_duration) > _DURATION_TOLERANCE_SECONDS:
            output_path.unlink()
            raise VerticalReframeError(
                f"Produced clip duration {produced_duration:.3f}s does not match "
                f"requested duration {expected_duration:.3f}s within tolerance "
                f"{_DURATION_TOLERANCE_SECONDS}s for {output_path}"
            )
        if produced_width != crop_width or produced_height != source_height:
            output_path.unlink()
            raise VerticalReframeError(
                f"Produced clip dimensions {produced_width}x{produced_height} do not "
                f"match the expected 9:16 crop {crop_width}x{source_height} for "
                f"{output_path}"
            )

        return ReframeResult(
            output_path=output_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            crop_width=crop_width,
            crop_height=source_height,
            crop_x1=x1,
        )
    finally:
        if cropped is not None:
            cropped.close()
        if clip is not None:
            clip.close()
        source.close()
