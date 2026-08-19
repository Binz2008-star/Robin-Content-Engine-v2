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

from robin_content_engine import vertical_reframe as vertical_reframe_module  # noqa: E402
from robin_content_engine.vertical_reframe import (  # noqa: E402
    VerticalReframeError,
    reframe_to_vertical,
)


@pytest.fixture(scope="module")
def source_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~10s synthetic landscape video+audio clip at a distinctive, wide
    16:9-ish resolution and non-default fps, wide enough for a real 9:16
    crop and long enough to exercise real interval extraction."""
    out = tmp_path_factory.mktemp("vertical_reframe") / "source.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=160x64:r=24:d=10",
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


def test_reframe_produces_centered_9_16_crop_by_default(
    source_video: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "out.mp4"

    result = reframe_to_vertical(source_video, output_path, start_seconds=2.0, end_seconds=6.0)

    # source is 160x64; expected crop width = floor_even(64 * 9/16) = 36
    assert result.crop_width == 36
    assert result.crop_height == 64
    # centered: max_x1 = 160 - 36 = 124, x1 = round(0.5 * 124) = 62
    assert result.crop_x1 == 62
    assert result.duration_seconds == pytest.approx(4.0, abs=1e-6)

    with VideoFileClip(str(output_path)) as produced:
        # the 9:16 crop is always delivered at the standard Shorts
        # resolution (1080x1920), never left at the tiny native crop size
        assert list(produced.size) == [1080, 1920]
        assert produced.duration == pytest.approx(4.0, abs=0.5)
        assert produced.fps == pytest.approx(24.0, abs=0.5)


def test_reframe_respects_horizontal_offset_ratio(source_video: Path, tmp_path: Path) -> None:
    left_output = tmp_path / "left.mp4"
    right_output = tmp_path / "right.mp4"

    left_result = reframe_to_vertical(
        source_video,
        left_output,
        start_seconds=0.0,
        end_seconds=2.0,
        horizontal_offset_ratio=0.0,
    )
    right_result = reframe_to_vertical(
        source_video,
        right_output,
        start_seconds=0.0,
        end_seconds=2.0,
        horizontal_offset_ratio=1.0,
    )

    assert left_result.crop_x1 == 0
    assert right_result.crop_x1 == 160 - 36


def test_rejects_invalid_horizontal_offset_ratio(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(VerticalReframeError, match="horizontal_offset_ratio"):
        reframe_to_vertical(
            source_video,
            tmp_path / "out.mp4",
            start_seconds=0.0,
            end_seconds=2.0,
            horizontal_offset_ratio=1.5,
        )


def test_rejects_output_with_wrong_duration_and_cleans_up_failed_attempt(
    source_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        vertical_reframe_module, "_probe_output", lambda path: (999.0, 36, 64)
    )
    output_path = tmp_path / "out.mp4"

    with pytest.raises(VerticalReframeError, match="duration"):
        reframe_to_vertical(source_video, output_path, start_seconds=2.0, end_seconds=6.0)

    assert not output_path.exists()


def test_rejects_output_with_wrong_dimensions_and_cleans_up_failed_attempt(
    source_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        vertical_reframe_module, "_probe_output", lambda path: (4.0, 999, 999)
    )
    output_path = tmp_path / "out.mp4"

    with pytest.raises(VerticalReframeError, match="dimensions"):
        reframe_to_vertical(source_video, output_path, start_seconds=2.0, end_seconds=6.0)

    assert not output_path.exists()


def test_source_file_is_unchanged(source_video: Path, tmp_path: Path) -> None:
    original_bytes = source_video.stat().st_size
    original_mtime = source_video.stat().st_mtime

    reframe_to_vertical(source_video, tmp_path / "out.mp4", start_seconds=1.0, end_seconds=3.0)

    assert source_video.stat().st_size == original_bytes
    assert source_video.stat().st_mtime == original_mtime


def test_refuses_to_overwrite_existing_output(source_video: Path, tmp_path: Path) -> None:
    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"already here")

    with pytest.raises(VerticalReframeError, match="already exists"):
        reframe_to_vertical(source_video, output_path, start_seconds=0.0, end_seconds=2.0)

    assert output_path.read_bytes() == b"already here"


def test_rejects_end_not_after_start(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(VerticalReframeError, match="end_seconds"):
        reframe_to_vertical(source_video, tmp_path / "out.mp4", start_seconds=5.0, end_seconds=5.0)


def test_rejects_missing_source_file(tmp_path: Path) -> None:
    with pytest.raises(VerticalReframeError, match="does not exist"):
        reframe_to_vertical(
            tmp_path / "gone.mp4", tmp_path / "out.mp4", start_seconds=0.0, end_seconds=1.0
        )


def test_rejects_end_beyond_source_duration(source_video: Path, tmp_path: Path) -> None:
    with pytest.raises(VerticalReframeError, match="exceeds source duration"):
        reframe_to_vertical(
            source_video, tmp_path / "out.mp4", start_seconds=0.0, end_seconds=999.0
        )


def test_rejects_source_too_narrow_for_9_16_crop(tmp_path_factory: pytest.TempPathFactory) -> None:
    """A source narrower than a 9:16 crop of its own height cannot be
    center-cropped without padding, which this static-crop MVP does not do."""
    narrow_source = tmp_path_factory.mktemp("narrow") / "narrow.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=20x64:r=24:d=3",
        "-c:v",
        "libx264",
        "-an",
        str(narrow_source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    with pytest.raises(VerticalReframeError, match="not wide enough"):
        reframe_to_vertical(
            narrow_source, tmp_path_factory.mktemp("out") / "out.mp4",
            start_seconds=0.0, end_seconds=2.0,
        )
