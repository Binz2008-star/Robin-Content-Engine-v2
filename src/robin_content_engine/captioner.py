from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from moviepy import VideoFileClip

from .transcription import TranscriptSegment

# Used as the codec/container tolerance for validating the produced
# output's actual duration against the source clip it was burned from -
# caption burn-in re-encodes video but must not change the clip's length.
_DURATION_TOLERANCE_SECONDS = 0.5


class CaptionError(Exception):
    pass


def _probe_output(path: Path) -> tuple[float, int, int]:
    with VideoFileClip(str(path)) as probe:
        width, height = probe.size
        return float(probe.duration), int(width), int(height)


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = round(max(0.0, seconds) * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, millis = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    """Render transcript segments as SRT subtitle text - the ASR's own
    transcribed words, verbatim, only segmented for readability. Segments
    with empty/whitespace-only text are skipped."""
    blocks = []
    index = 1
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        blocks.append(
            f"{index}\n"
            f"{_format_srt_timestamp(segment.start_seconds)} --> "
            f"{_format_srt_timestamp(segment.end_seconds)}\n"
            f"{text}\n"
        )
        index += 1
    return "\n".join(blocks)


@dataclass(frozen=True)
class CaptionResult:
    output_path: Path
    segment_count: int


def burn_captions(
    video_path: Path,
    output_path: Path,
    segments: list[TranscriptSegment],
) -> CaptionResult:
    """Burn readable captions from segments onto video_path, writing a new
    local MP4 at output_path (H.264 video, re-encoded; audio stream-copied
    unchanged). Uses ffmpeg's `subtitles` filter (libass) against a
    temporary SRT file - no new heavy dependency, since ffmpeg is already
    bundled via imageio-ffmpeg/moviepy and this build supports libass.

    Never modifies video_path. Never overwrites an existing output_path.
    After encoding, the produced file's actual duration and frame
    dimensions are probed and checked against video_path's own duration/
    dimensions (captioning must not resize or trim the clip); a mismatch
    deletes the just-created output (never video_path) and raises
    CaptionError.
    """
    if not video_path.is_file():
        raise CaptionError(f"Video file does not exist: {video_path}")
    if output_path.exists():
        raise CaptionError(
            f"Output file already exists, refusing to overwrite: {output_path}"
        )

    readable_segments = [s for s in segments if s.text.strip()]
    if not readable_segments:
        raise CaptionError("No non-empty transcript segments to caption.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with VideoFileClip(str(video_path)) as source:
        source_duration = float(source.duration)
        source_width, source_height = source.size

    srt_path = output_path.with_suffix(".srt")
    if srt_path.exists():
        raise CaptionError(
            f"Temporary subtitle file already exists, refusing to overwrite: {srt_path}"
        )
    srt_path.write_text(segments_to_srt(readable_segments), encoding="utf-8")

    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        # The subtitles= filter argument treats ':' as an option separator,
        # so an absolute path (which contains ':' only on Windows drive
        # letters, not relevant here) needs its own colons/backslashes
        # escaped. Deterministic filenames from this codebase never
        # contain other filter-special characters.
        escaped_srt_path = str(srt_path).replace("\\", "\\\\").replace(":", "\\:")
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles={escaped_srt_path}",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise CaptionError(f"ffmpeg caption burn-in failed: {result.stderr[-2000:]}")
    finally:
        srt_path.unlink(missing_ok=True)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise CaptionError(f"Caption burn-in completed without producing output: {output_path}")

    produced_duration, produced_width, produced_height = _probe_output(output_path)
    if abs(produced_duration - source_duration) > _DURATION_TOLERANCE_SECONDS:
        output_path.unlink()
        raise CaptionError(
            f"Produced captioned clip duration {produced_duration:.3f}s does not match "
            f"source duration {source_duration:.3f}s within tolerance "
            f"{_DURATION_TOLERANCE_SECONDS}s for {output_path}"
        )
    if produced_width != source_width or produced_height != source_height:
        output_path.unlink()
        raise CaptionError(
            f"Produced captioned clip dimensions {produced_width}x{produced_height} do not "
            f"match source dimensions {source_width}x{source_height} for {output_path}"
        )

    return CaptionResult(output_path=output_path, segment_count=len(readable_segments))
