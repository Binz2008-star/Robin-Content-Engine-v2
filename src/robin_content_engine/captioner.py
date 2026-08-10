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

# FPS tolerance for the same reason clip_cutter/vertical_reframe use one:
# negligible container/codec rounding, not an actual frame-rate change.
_FPS_TOLERANCE = 0.5


class CaptionError(Exception):
    pass


def _probe_output(path: Path) -> tuple[float, int, int, float]:
    with VideoFileClip(str(path)) as probe:
        width, height = probe.size
        return float(probe.duration), int(width), int(height), float(probe.fps)


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


def escape_subtitles_filter_path(path: Path) -> str:
    """Escape and quote a filesystem path for use as ffmpeg's `subtitles=`
    filter option value, per ffmpeg's own filtergraph escaping rules -
    this has to be correct on the operator's Windows machine, where real
    paths look like `X:\\content engine\\Robin-Content-Engine-v2\\work\\
    highlights\\...srt` (a drive-letter colon, backslash separators, and
    spaces).

    Backslashes are doubled, the colon from a drive letter is
    backslash-escaped (otherwise ffmpeg's filter option parser treats
    ':' as a key=value separator), and the whole value is wrapped in
    single quotes and passed via the explicit `filename=` sub-option -
    single-quoting also protects spaces and any other filter-special
    characters (',', ';', '[', ']') without needing to enumerate them.
    A literal single quote in the path can't be safely represented this
    way, so that case fails loudly instead of producing a silently
    broken ffmpeg command line - not expected for this codebase's own
    deterministic filenames.
    """
    raw = str(path)
    if "'" in raw:
        raise CaptionError(
            f"Path contains a single quote, which cannot be safely passed to ffmpeg's "
            f"subtitles filter: {path}"
        )
    escaped = raw.replace("\\", "\\\\").replace(":", "\\:")
    return f"filename='{escaped}'"


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
    After encoding, the produced file's actual duration, frame dimensions,
    and FPS are probed and checked against video_path's own values
    (captioning must not resize, trim, or resample the clip). Any
    failure past this point - a non-zero ffmpeg exit, a file that probes
    as empty, a probe that itself raises (e.g. a partially-written/corrupt
    file from an interrupted encode), or a mismatched
    duration/dimensions/fps - deletes only the output this attempt just
    created (never video_path, never a pre-existing file) and raises
    CaptionError, so the deterministic output filename remains free for a
    retry rather than being permanently blocked by a leftover partial
    file.
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
        source_fps = float(source.fps)

    srt_path = output_path.with_suffix(".srt")
    if srt_path.exists():
        raise CaptionError(
            f"Temporary subtitle file already exists, refusing to overwrite: {srt_path}"
        )
    srt_path.write_text(segments_to_srt(readable_segments), encoding="utf-8")

    def _cleanup_bad_output() -> None:
        # Only ever removes the output this call just created (or was in
        # the process of creating) - video_path and any pre-existing file
        # are never touched (the pre-existing-file case already raised
        # and returned above, before any of this ran).
        output_path.unlink(missing_ok=True)

    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles={escape_subtitles_filter_path(srt_path)}",
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
            _cleanup_bad_output()
            raise CaptionError(f"ffmpeg caption burn-in failed: {result.stderr[-2000:]}")
    finally:
        srt_path.unlink(missing_ok=True)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        _cleanup_bad_output()
        raise CaptionError(f"Caption burn-in completed without producing output: {output_path}")

    try:
        produced_duration, produced_width, produced_height, produced_fps = _probe_output(
            output_path
        )
    except Exception as exc:
        _cleanup_bad_output()
        raise CaptionError(
            f"Failed to probe produced captioned clip {output_path}: {exc}"
        ) from exc

    if abs(produced_duration - source_duration) > _DURATION_TOLERANCE_SECONDS:
        _cleanup_bad_output()
        raise CaptionError(
            f"Produced captioned clip duration {produced_duration:.3f}s does not match "
            f"source duration {source_duration:.3f}s within tolerance "
            f"{_DURATION_TOLERANCE_SECONDS}s for {output_path}"
        )
    if produced_width != source_width or produced_height != source_height:
        _cleanup_bad_output()
        raise CaptionError(
            f"Produced captioned clip dimensions {produced_width}x{produced_height} do not "
            f"match source dimensions {source_width}x{source_height} for {output_path}"
        )
    if abs(produced_fps - source_fps) > _FPS_TOLERANCE:
        _cleanup_bad_output()
        raise CaptionError(
            f"Produced captioned clip FPS {produced_fps:.3f} does not match source FPS "
            f"{source_fps:.3f} within tolerance {_FPS_TOLERANCE} for {output_path}"
        )

    return CaptionResult(output_path=output_path, segment_count=len(readable_segments))
