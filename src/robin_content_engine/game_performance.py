"""Per-game performance report - a read-only, advisory analysis of the
channel's OWN published-video history.

Answers "which game's videos actually get watched?" so the operator can
decide what to record and queue next. Purely advisory: it never schedules,
uploads, writes to any database, or changes any job/rights/upload state -
it only reads youtube_videos (current PUBLIC videos with a view count),
left-joined to video_queue so engine-produced uploads are flagged and their
original capture title can be used for game detection.

Game detection reuses channel_metadata.detect_game, which is deliberately
conservative (an ambiguous capture name is never guessed); videos it cannot
classify are grouped under UNCLASSIFIED rather than dropped, so the report
never silently hides part of the channel.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import psycopg

from .channel_metadata import detect_game
from .config import Settings

UNCLASSIFIED = "Unclassified"

# Below this many videos a game's median is too noisy to act on, so the
# recommendation says so instead of sounding certain.
SMALL_SAMPLE = 5

# YouTube accepts Shorts up to 3 minutes; anything longer is long-form.
SHORT_MAX_SECONDS = 180

VideoFormat = Literal["all", "short", "long"]
_FORMATS: tuple[str, ...] = ("all", "short", "long")


class GamePerformanceError(RuntimeError):
    """Raised for invalid analysis parameters (never for an empty history -
    an empty history is a normal, well-formed report)."""


@dataclass(frozen=True)
class VideoStat:
    video_id: str
    title: str
    source_title: str | None
    tags: tuple[str, ...]
    duration_seconds: int | None
    view_count: int
    like_count: int | None
    produced_by_engine: bool


@dataclass(frozen=True)
class GameStat:
    game: str
    count: int
    engine_count: int
    total_views: int
    median_views: int
    mean_views: float
    median_likes: int | None
    like_rate: float | None  # total likes / total views, among videos with likes


@dataclass(frozen=True)
class GamePerformanceReport:
    generated_at: datetime
    video_format: str
    sample_count: int
    total_views: int
    by_game: list[GameStat]
    recommendation: str


def classify_game(video: VideoStat) -> str:
    """Best-effort game for one video. The engine's original capture title is
    the most reliable signal (the published title may be AI-rewritten, e.g.
    Arabic with no game name), then the published title, then its tags."""
    for candidate in (video.source_title, video.title, " ".join(video.tags)):
        if candidate:
            game = detect_game(candidate)
            if game:
                return game
    return UNCLASSIFIED


def analyze_game_performance(
    videos: Sequence[VideoStat],
    *,
    video_format: VideoFormat = "all",
    min_count: int = 1,
) -> GamePerformanceReport:
    """Deterministic, pure analysis. Groups videos by detected game, ranks
    games by median views (ties: mean views, then name), and keeps only
    games backed by at least `min_count` videos. Unclassified videos always
    sort last so a large bucket of unknowns never reads as a recommendation.
    Never raises for an empty history."""
    if video_format not in _FORMATS:
        raise GamePerformanceError(f"video_format must be one of {', '.join(_FORMATS)}.")
    if min_count < 1:
        raise GamePerformanceError("min_count must be >= 1.")

    selected = [video for video in videos if _matches_format(video, video_format)]

    groups: dict[str, list[VideoStat]] = defaultdict(list)
    for video in selected:
        groups[classify_game(video)].append(video)

    by_game = sorted(
        (
            _game_stat(game, group)
            for game, group in groups.items()
            if len(group) >= min_count
        ),
        key=lambda s: (s.game == UNCLASSIFIED, -s.median_views, -s.mean_views, s.game),
    )

    return GamePerformanceReport(
        generated_at=datetime.now(UTC),
        video_format=video_format,
        sample_count=len(selected),
        total_views=sum(video.view_count for video in selected),
        by_game=by_game,
        recommendation=_build_recommendation(by_game),
    )


def fetch_video_stats(settings: Settings) -> list[VideoStat]:
    """Read-only fetch of the channel's current PUBLIC videos that have a
    view count, each flagged with whether the engine produced it. A pure
    SELECT - never writes to any database."""
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            """
            SELECT v.video_id,
                   v.title,
                   q.source_title,
                   v.tags,
                   v.duration_seconds,
                   v.view_count,
                   v.like_count,
                   (q.id IS NOT NULL) AS produced_by_engine
            FROM youtube_videos v
            LEFT JOIN video_queue q ON q.youtube_id = v.video_id
            WHERE v.is_current = TRUE
              AND v.view_count IS NOT NULL
              AND v.privacy_status = 'public'
            ORDER BY v.published_at ASC NULLS LAST, v.video_id ASC
            """
        ).fetchall()

    result: list[VideoStat] = []
    for video_id, title, source_title, tags, duration, views, likes, engine in rows:
        if not isinstance(views, int):
            continue
        result.append(
            VideoStat(
                video_id=str(video_id),
                title=str(title or ""),
                source_title=source_title if isinstance(source_title, str) else None,
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                duration_seconds=duration if isinstance(duration, int) else None,
                view_count=views,
                like_count=likes if isinstance(likes, int) else None,
                produced_by_engine=bool(engine),
            )
        )
    return result


def build_game_performance_report(
    settings: Settings,
    *,
    video_format: VideoFormat = "all",
    min_count: int = 1,
) -> GamePerformanceReport:
    """Fetch the channel's published-video history and analyze it per game.
    Read-only end to end."""
    return analyze_game_performance(
        fetch_video_stats(settings), video_format=video_format, min_count=min_count
    )


def _matches_format(video: VideoStat, video_format: str) -> bool:
    if video_format == "all":
        return True
    # A video with no known duration cannot be placed in either bucket.
    if video.duration_seconds is None:
        return False
    is_short = video.duration_seconds <= SHORT_MAX_SECONDS
    return is_short if video_format == "short" else not is_short


def _game_stat(game: str, group: list[VideoStat]) -> GameStat:
    views = [video.view_count for video in group]
    liked = [video for video in group if video.like_count is not None]
    likes = [video.like_count for video in liked if video.like_count is not None]
    liked_views = sum(video.view_count for video in liked)
    return GameStat(
        game=game,
        count=len(group),
        engine_count=sum(1 for video in group if video.produced_by_engine),
        total_views=sum(views),
        median_views=_median(views),
        mean_views=statistics.mean(views),
        median_likes=_median(likes) if likes else None,
        like_rate=(sum(likes) / liked_views) if likes and liked_views > 0 else None,
    )


def _median(values: list[int]) -> int:
    """Median of a non-empty list of ints (even-count medians averaged and
    rounded to a whole number)."""
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[mid]
    return round((sorted_values[mid - 1] + sorted_values[mid]) / 2)


def _build_recommendation(by_game: list[GameStat]) -> str:
    classified = [stat for stat in by_game if stat.game != UNCLASSIFIED]
    if not classified:
        return (
            "Not enough classified public-video history yet to compare games. "
            "Run 'robin-engine youtube-sync' after publishing a few videos."
        )
    top = classified[0]
    caveat = (
        " Small sample - treat as a signal, not a conclusion."
        if top.count < SMALL_SAMPLE
        else ""
    )
    if len(classified) == 1:
        return (
            f"Only one game has history so far: {top.game} "
            f"(median {top.median_views} views over {top.count} video(s)).{caveat}"
        )
    runner_up = classified[1]
    return (
        f"{top.game} performs best (median {top.median_views} views over "
        f"{top.count} video(s)), ahead of {runner_up.game} "
        f"(median {runner_up.median_views}). Prioritise {top.game} captures.{caveat}"
    )
