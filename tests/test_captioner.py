from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402
from moviepy import VideoFileClip  # noqa: E402

from robin_content_engine import captioner as captioner_module  # noqa: E402
from robin_content_engine.captioner import (  # noqa: E402
    CaptionError,
    burn_captions,
    escape_subtitles_filter_path,
    segments_to_srt,
)
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402


@pytest.fixture(scope="module")
def source_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~4s synthetic video+audio clip - long enough to hold two caption
    segments."""
    out = tmp_path_factory.mktemp("captioner") / "source.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=64x64:r=10:d=4",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:r=16000:d=4",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture
def segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there"),
        TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="general kenobi"),
    ]


def test_segments_to_srt_format() -> None:
    srt = segments_to_srt(
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="hi"),
            TranscriptSegment(start_seconds=61.25, end_seconds=62.0, text="bye"),
        ]
    )

    assert "1\n00:00:00,000 --> 00:00:01,500\nhi" in srt
    assert "2\n00:01:01,250 --> 00:01:02,000\nbye" in srt


def test_segments_to_srt_skips_blank_text() -> None:
    srt = segments_to_srt(
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="   "),
            TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="real text"),
        ]
    )

    assert "real text" in srt
    assert srt.count("-->") == 1


def test_burn_captions_produces_output_matching_source_duration_and_size(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"

    with VideoFileClip(str(source_video)) as source:
        expected_duration = float(source.duration)
        expected_size = list(source.size)

    result = burn_captions(source_video, output_path, segments)

    assert result.output_path == output_path
    assert result.segment_count == 2
    assert output_path.is_file()
    assert output_path.stat().st_size > 0

    with VideoFileClip(str(output_path)) as produced:
        assert produced.duration == pytest.approx(expected_duration, abs=0.5)
        assert list(produced.size) == expected_size


def test_skips_empty_segments_and_reports_count(
    source_video: Path, tmp_path: Path
) -> None:
    mixed_segments = [
        TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text=""),
        TranscriptSegment(start_seconds=1.0, end_seconds=2.0, text="  "),
        TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="only real line"),
    ]

    result = burn_captions(source_video, tmp_path / "out.mp4", mixed_segments)

    assert result.segment_count == 1


def test_rejects_all_empty_segments(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(CaptionError, match="No non-empty"):
        burn_captions(
            source_video,
            tmp_path / "out.mp4",
            [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="   ")],
        )


def test_rejects_missing_video_file(
    segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    with pytest.raises(CaptionError, match="does not exist"):
        burn_captions(tmp_path / "gone.mp4", tmp_path / "out.mp4", segments)


def test_refuses_to_overwrite_existing_output(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"already here")

    with pytest.raises(CaptionError, match="already exists"):
        burn_captions(source_video, output_path, segments)

    assert output_path.read_bytes() == b"already here"


def test_source_video_is_unchanged(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    original_bytes = source_video.stat().st_size
    original_mtime = source_video.stat().st_mtime

    burn_captions(source_video, tmp_path / "out.mp4", segments)

    assert source_video.stat().st_size == original_bytes
    assert source_video.stat().st_mtime == original_mtime


def test_rejects_output_with_wrong_duration_and_cleans_up_failed_attempt(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captioner_module, "_probe_output", lambda path: (999.0, 64, 64, 10.0))
    output_path = tmp_path / "out.mp4"

    with pytest.raises(CaptionError, match="duration"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()


def test_rejects_output_with_wrong_dimensions_and_cleans_up_failed_attempt(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captioner_module, "_probe_output", lambda path: (4.0, 999, 999, 10.0))
    output_path = tmp_path / "out.mp4"

    with pytest.raises(CaptionError, match="dimensions"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()


def test_rejects_output_with_wrong_fps_and_cleans_up_failed_attempt(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captioner_module, "_probe_output", lambda path: (4.0, 64, 64, 999.0))
    output_path = tmp_path / "out.mp4"

    with pytest.raises(CaptionError, match="FPS"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()


def test_no_leftover_srt_file(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"

    burn_captions(source_video, output_path, segments)

    assert not output_path.with_suffix(".srt").exists()


# ---------------------------------------------------------------------------
# CTO review round 1: partial-output cleanup, probe-failure cleanup, and
# path escaping (regression coverage)
# ---------------------------------------------------------------------------


def test_cleans_up_partial_output_on_ffmpeg_failure(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed ffmpeg run can still have written a partial/corrupt file to
    the output path before exiting non-zero. burn_captions() must delete
    that partial output (never video_path) so a retry at the same
    deterministic path isn't blocked by "already exists"."""
    output_path = tmp_path / "out.mp4"

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # cmd's last element is the output path this call was asked to
        # produce - simulate ffmpeg having written a partial file before
        # failing.
        Path(cmd[-1]).write_bytes(b"partial, corrupt output")
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(captioner_module.subprocess, "run", fake_run)

    with pytest.raises(CaptionError, match="ffmpeg caption burn-in failed"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()
    # the real source file is a different fixture instance entirely and was
    # never passed to fake_run as the output target - unaffected.
    assert source_video.is_file()


def test_hung_ffmpeg_is_bounded_and_cleans_up_partial_output(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung ffmpeg (subprocess.TimeoutExpired) must fail the stage with
    a clear CaptionError - cleaning up any partial output so the retry
    at the same deterministic path is possible - rather than blocking
    the pipeline forever."""
    output_path = tmp_path / "out.mp4"

    def hung_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(cmd[-1]).write_bytes(b"partial output before the hang")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=600)

    monkeypatch.setattr(captioner_module.subprocess, "run", hung_run)

    with pytest.raises(CaptionError, match="timed out after"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()
    assert not output_path.with_suffix(".srt").exists()
    assert source_video.is_file()


def test_cleans_up_output_when_post_encode_probe_raises(
    source_video: Path,
    segments: list[TranscriptSegment],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successfully-exited ffmpeg can still leave a file that doesn't
    parse as valid video (e.g. interrupted write, disk full mid-mux).
    burn_captions() must catch a probe failure, clean up, and raise
    CaptionError rather than letting a raw exception escape."""

    def failing_probe(path: Path) -> tuple[float, int, int, float]:
        raise RuntimeError("simulated corrupt output, cannot probe")

    monkeypatch.setattr(captioner_module, "_probe_output", failing_probe)
    output_path = tmp_path / "out.mp4"

    with pytest.raises(CaptionError, match="Failed to probe"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()


def test_escape_subtitles_filter_path_on_windows_style_path() -> None:
    windows_path = Path(
        r"X:\content engine\Robin-Content-Engine-v2\work\highlights\job-19.srt"
    )

    escaped = escape_subtitles_filter_path(windows_path)

    assert escaped == (
        r"filename='X\:\\content engine\\Robin-Content-Engine-v2\\work\\highlights"
        r"\\job-19.srt'"
    )
    # the drive-letter colon must not survive unescaped - ffmpeg's filter
    # option parser would otherwise treat it as a key=value separator
    assert "X:" not in escaped
    assert escaped.startswith("filename='")
    assert escaped.endswith("'")


def test_escape_subtitles_filter_path_rejects_literal_single_quote() -> None:
    with pytest.raises(CaptionError, match="single quote"):
        escape_subtitles_filter_path(Path("/tmp/it's-a-path.srt"))


# ---------------------------------------------------------------------------
# AI-suggested opening hook caption
# ---------------------------------------------------------------------------


def test_segments_to_srt_with_hook_renders_hook_as_first_block(
    segments: list[TranscriptSegment],
) -> None:
    srt = segments_to_srt(segments, hook_text="nice clutch")

    assert srt.count("-->") == 3
    blocks = [block.strip() for block in srt.split("\n\n")]
    # The hook is the FIRST subtitle block, spanning the opening window.
    assert blocks[0].startswith("1\n00:00:00,000 --> ")
    assert blocks[0].endswith("\nnice clutch")
    # The ASR captions follow, renumbered from 2.
    assert "2\n00:00:00,000 --> 00:00:02,000\nhello there" in srt
    assert "3\n00:00:02,000 --> 00:00:04,000\ngeneral kenobi" in srt


def test_hook_display_window_clamped_to_first_segment_start() -> None:
    srt = segments_to_srt(
        [
            TranscriptSegment(start_seconds=8.0, end_seconds=10.0, text="late speech"),
        ],
        hook_text="clutch",
    )

    # Hook capped at _HOOK_MAX_SECONDS (3.0), never spanning the gap to 8.0s.
    assert "00:00:00,000 --> 00:00:03,000" in srt
    assert "00:00:08,000 --> 00:00:10,000" in srt


def test_hook_no_speech_fixed_window() -> None:
    srt = segments_to_srt([], hook_text="only a hook")

    # No ASR segments: the hook still renders, over the fixed no-speech
    # window (_HOOK_NO_SPEECH_SECONDS = 2.0).
    assert srt.count("-->") == 1
    assert "1\n00:00:00,000 --> 00:00:02,000\nonly a hook" in srt


def test_blank_hook_treated_as_no_hook(segments: list[TranscriptSegment]) -> None:
    plain = segments_to_srt(segments)
    with_hook = segments_to_srt(segments, hook_text="   \n  ")
    assert with_hook == plain
    assert with_hook.startswith("1\n00:00:00,000 --> 00:00:02,000\nhello there")


def test_burn_captions_accepts_hook_and_counts_asr_segments_only(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    output_path = tmp_path / "out-hooked.mp4"
    result = burn_captions(source_video, output_path, segments, hook_text="nice clutch")

    assert result.segment_count == 2
    assert result.output_path == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0


def test_burn_captions_still_rejects_all_empty_segments_with_hook(
    source_video: Path, tmp_path: Path
) -> None:
    # A hook alone never turns a speechless clip into a captioned one.
    with pytest.raises(CaptionError, match="No non-empty transcript segments"):
        burn_captions(
            source_video,
            tmp_path / "out.mp4",
            [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="   ")],
            hook_text="nice clutch",
        )
