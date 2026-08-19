from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scenedetect import AdaptiveDetector, SceneManager, open_video


class SceneDetectionError(Exception):
    pass


@dataclass(frozen=True)
class SceneDetectorConfig:
    """Tunables for AdaptiveDetector, exposed instead of buried as literals.

    Defaults match PySceneDetect's own AdaptiveDetector defaults. downscale=None
    keeps the library's auto_downscale behavior; set an explicit integer to
    override it (1 = no downscale, 2 = half resolution, etc.).
    """

    adaptive_threshold: float = 3.0
    min_scene_len_frames: int = 15
    window_width: int = 2
    min_content_val: float = 15.0
    downscale: int | None = None


@dataclass(frozen=True)
class SceneBoundary:
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int


def detect_scenes(
    video_path: Path,
    config: SceneDetectorConfig | None = None,
) -> list[SceneBoundary]:
    """Detect scene boundaries using PySceneDetect's AdaptiveDetector.

    Detection only - never invokes PySceneDetect's video-splitting or
    rendering functions. AdaptiveDetector's rolling-average normalization
    is chosen (over ContentDetector's fixed threshold) specifically to
    mitigate false cuts from fast camera movement in high-motion gameplay.
    """
    config = config or SceneDetectorConfig()
    if not video_path.is_file():
        raise SceneDetectionError(f"Source video does not exist: {video_path}")

    try:
        video = open_video(str(video_path))
    except Exception as exc:
        raise SceneDetectionError(f"Could not open video {video_path}: {exc}") from exc

    scene_manager = SceneManager()
    scene_manager.add_detector(
        AdaptiveDetector(
            adaptive_threshold=config.adaptive_threshold,
            min_scene_len=config.min_scene_len_frames,
            window_width=config.window_width,
            min_content_val=config.min_content_val,
        )
    )
    if config.downscale is not None:
        scene_manager.auto_downscale = False
        scene_manager.downscale = config.downscale

    try:
        scene_manager.detect_scenes(video)
    except Exception as exc:
        raise SceneDetectionError(f"Scene detection failed for {video_path}: {exc}") from exc

    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        duration = video.duration
        if duration is None or duration.frame_num <= 0:
            raise SceneDetectionError(f"Video has no decodable frames: {video_path}")
        return [
            SceneBoundary(
                start_seconds=0.0,
                end_seconds=duration.seconds,
                start_frame=0,
                end_frame=duration.frame_num,
            )
        ]

    return [
        SceneBoundary(
            start_seconds=start.seconds,
            end_seconds=end.seconds,
            start_frame=start.frame_num,
            end_frame=end.frame_num,
        )
        for start, end in scene_list
    ]
