from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moviepy import VideoFileClip

# Used both to guard against negligible floating-point accumulation when
# checking a requested end against the source's real duration, and as the
# explicit codec/container tolerance for validating the produced output's
# actual duration against the requested interval.
_DURATION_TOLERANCE_SECONDS = 0.5


class ClipCutError(Exception):
    pass


def _probe_output_duration(path: Path) -> float:
    with VideoFileClip(str(path)) as probe:
        return float(probe.duration)


@dataclass(frozen=True)
class CutResult:
    output_path: Path
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def cut_clip(
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    end_seconds: float,
) -> CutResult:
    """Extract [start_seconds, end_seconds) from source_path into a new
    local MP4 at output_path (H.264 video, AAC audio), preserving the
    source's framing/resolution/FPS - no crop, no resize, no vertical
    reframe. Never modifies, moves, renames, or deletes source_path.
    Never overwrites an existing output_path - fails instead, so a caller
    must choose a different (e.g. deterministically suffixed) path rather
    than silently clobbering a prior cut.

    After encoding, the produced file's actual duration is probed and
    checked against the requested interval within
    _DURATION_TOLERANCE_SECONDS. A file that exists and is non-empty but
    has the wrong duration is not a success: it is deleted (only the
    output this attempt just created - the source is never touched) and
    ClipCutError is raised, so the deterministic output filename remains
    free for a retry.
    """
    if end_seconds <= start_seconds:
        raise ClipCutError("end_seconds must be greater than start_seconds")
    if not source_path.is_file():
        raise ClipCutError(f"Source file does not exist: {source_path}")
    if output_path.exists():
        raise ClipCutError(f"Output file already exists, refusing to overwrite: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = VideoFileClip(str(source_path))
    clip = None
    try:
        if not source.duration or source.duration <= 0:
            raise ClipCutError(f"Source video has no usable duration: {source_path}")
        if end_seconds > source.duration + _DURATION_TOLERANCE_SECONDS:
            raise ClipCutError(
                f"Requested end_seconds {end_seconds} exceeds source duration "
                f"{source.duration} for {source_path}"
            )

        clip = source.subclipped(start_seconds, min(end_seconds, source.duration))
        # fps intentionally omitted: moviepy's @use_clip_fps_by_default
        # falls back to the clip's own native fps (i.e. the source's),
        # preserving it rather than resampling to an arbitrary value.
        clip.write_videofile(
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
            raise ClipCutError(f"Clip cut completed without producing output: {output_path}")

        expected_duration = min(end_seconds, source.duration) - start_seconds
        produced_duration = _probe_output_duration(output_path)
        if abs(produced_duration - expected_duration) > _DURATION_TOLERANCE_SECONDS:
            output_path.unlink()
            raise ClipCutError(
                f"Produced clip duration {produced_duration:.3f}s does not match "
                f"requested duration {expected_duration:.3f}s within tolerance "
                f"{_DURATION_TOLERANCE_SECONDS}s for {output_path}"
            )

        return CutResult(
            output_path=output_path, start_seconds=start_seconds, end_seconds=end_seconds
        )
    finally:
        if clip is not None:
            clip.close()
        source.close()
