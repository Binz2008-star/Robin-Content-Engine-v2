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

from robin_content_engine.clip_cutter import ClipCutError, cut_clip  # noqa: E402


@pytest.fixture(scope="module")
def source_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~10s synthetic video+audio clip at a distinctive, non-default fps and
    resolution, so preservation of both can be verified against defaults."""
    out = tmp_path_factory.mktemp("clip_cutter") / "source.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=96x64:r=24:d=10",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:r=16000:d=10",
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


def test_cut_clip_produces_output_with_expected_duration(
    source_video: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"

    result = cut_clip(source_video, output_path, start_seconds=2.0, end_seconds=6.0)

    assert result.output_path == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
    assert result.duration_seconds == pytest.approx(4.0, abs=1e-6)

    with VideoFileClip(str(output_path)) as produced:
        assert produced.duration == pytest.approx(4.0, abs=0.5)


def test_source_file_is_unchanged(source_video: Path, tmp_path: Path) -> None:
    original_bytes = source_video.stat().st_size
    original_mtime = source_video.stat().st_mtime

    cut_clip(source_video, tmp_path / "out.mp4", start_seconds=1.0, end_seconds=3.0)

    assert source_video.stat().st_size == original_bytes
    assert source_video.stat().st_mtime == original_mtime


def test_refuses_to_overwrite_existing_output(source_video: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"already here")

    with pytest.raises(ClipCutError, match="already exists"):
        cut_clip(source_video, output_path, start_seconds=0.0, end_seconds=2.0)

    assert output_path.read_bytes() == b"already here"


def test_rejects_end_not_after_start(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(ClipCutError, match="end_seconds"):
        cut_clip(source_video, tmp_path / "out.mp4", start_seconds=5.0, end_seconds=5.0)


def test_rejects_missing_source_file(tmp_path: Path) -> None:
    with pytest.raises(ClipCutError, match="does not exist"):
        cut_clip(
            tmp_path / "gone.mp4", tmp_path / "out.mp4", start_seconds=0.0, end_seconds=1.0
        )


def test_rejects_end_beyond_source_duration(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(ClipCutError, match="exceeds source duration"):
        cut_clip(source_video, tmp_path / "out.mp4", start_seconds=0.0, end_seconds=999.0)
