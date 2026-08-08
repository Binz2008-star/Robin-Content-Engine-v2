from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from robin_content_engine.scene_detector import (  # noqa: E402
    SceneDetectionError,
    SceneDetectorConfig,
    detect_scenes,
)


def _write_two_segment_video(path: Path, *, fps: int = 10, seconds_each: int = 2) -> None:
    """A short synthetic clip with one obvious hard cut: solid black, then
    solid white. Small resolution keeps encode/decode fast in CI."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    width, height = 64, 64
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    black = np.zeros((height, width, 3), dtype=np.uint8)
    white = np.full((height, width, 3), 255, dtype=np.uint8)
    for _ in range(fps * seconds_each):
        writer.write(black)
    for _ in range(fps * seconds_each):
        writer.write(white)
    writer.release()


@pytest.fixture
def two_segment_video(tmp_path: Path) -> Path:
    video_path = tmp_path / "cut.mp4"
    _write_two_segment_video(video_path)
    return video_path


def test_detect_scenes_returns_structured_boundaries(two_segment_video: Path) -> None:
    scenes = detect_scenes(two_segment_video, SceneDetectorConfig(min_scene_len_frames=5))

    assert len(scenes) >= 1
    for scene in scenes:
        assert scene.start_seconds >= 0.0
        assert scene.end_seconds > scene.start_seconds
        assert scene.start_frame >= 0
        assert scene.end_frame > scene.start_frame

    # Boundaries must be contiguous and cover the whole video from 0.
    assert scenes[0].start_seconds == 0.0
    assert scenes[0].start_frame == 0
    for prev, nxt in pairwise(scenes):
        assert nxt.start_frame == prev.end_frame


def test_detect_scenes_finds_the_hard_cut(two_segment_video: Path) -> None:
    scenes = detect_scenes(two_segment_video, SceneDetectorConfig(min_scene_len_frames=5))

    # A black->white hard cut at ~2s should be detected as a scene boundary,
    # i.e. more than one scene, with the break landing near the 2s mark.
    assert len(scenes) >= 2
    assert any(1.5 <= s.end_seconds <= 2.5 for s in scenes[:-1])


def test_detect_scenes_raises_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.mp4"
    with pytest.raises(SceneDetectionError, match="does not exist"):
        detect_scenes(missing)


def test_detect_scenes_raises_on_invalid_video(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-video.mp4"
    bogus.write_text("this is not a video file")
    with pytest.raises(SceneDetectionError):
        detect_scenes(bogus)


def test_detect_scenes_has_no_rendering_side_effects(two_segment_video: Path) -> None:
    parent = two_segment_video.parent
    before = set(parent.iterdir())

    detect_scenes(two_segment_video)

    after = set(parent.iterdir())
    assert after == before, "detect_scenes must not write any files (no splitting/rendering)"
