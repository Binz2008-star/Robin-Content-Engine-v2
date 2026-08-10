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
    monkeypatch.setattr(captioner_module, "_probe_output", lambda path: (999.0, 64, 64))
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
    monkeypatch.setattr(captioner_module, "_probe_output", lambda path: (4.0, 999, 999))
    output_path = tmp_path / "out.mp4"

    with pytest.raises(CaptionError, match="dimensions"):
        burn_captions(source_video, output_path, segments)

    assert not output_path.exists()


def test_no_leftover_srt_file(
    source_video: Path, segments: list[TranscriptSegment], tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"

    burn_captions(source_video, output_path, segments)

    assert not output_path.with_suffix(".srt").exists()
