"""Posting-time recommendation - a read-only, advisory analysis of the
channel's OWN published-video history.

Suggests which day-of-week / hour-of-day windows have historically
performed best (by median views) for scheduling new uploads. Purely
advisory: it never schedules anything, never uploads, never writes to any
database, and never changes any job/rights/upload state - it only reads
youtube_videos (published_at + view_count of current PUBLIC videos) and
reports.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from .config import Settings

# The channel targets a UAE audience; Asia/Dubai has no DST, so weekday/hour
# bucketing is stable year-round. Overridable per call (CLI --timezone).
_DEFAULT_TIMEZONE = ZoneInfo("Asia/Dubai")

# ISO weekday 1=Monday .. 7=Sunday, indexed weekday-1.
WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class PostingTimeError(RuntimeError):
    """Raised for invalid analysis parameters (never for an empty history -
    an empty history is a normal, well-formed report)."""


@dataclass(frozen=True)
class PostingWindow:
    weekday: int  # ISO weekday, 1=Monday .. 7=Sunday
    hour: int  # 0-23 local hour
    count: int
    median_views: int
    mean_views: float


@dataclass(frozen=True)
class WeekdayStat:
    weekday: int
    count: int
    median_views: int
    mean_views: float


@dataclass(frozen=True)
class HourStat:
    hour: int
    count: int
    median_views: int
    mean_views: float


@dataclass(frozen=True)
class PostingReport:
    generated_at: datetime
    timezone: str
    sample_count: int
    total_views: int
    best_windows: list[PostingWindow]
    by_weekday: list[WeekdayStat]
    by_hour: list[HourStat]
    recommendation: str


def analyze_posting_windows(
    videos: Sequence[tuple[datetime, int]],
    *,
    timezone: Any = _DEFAULT_TIMEZONE,
    min_count: int = 1,
    top_n: int = 5,
) -> PostingReport:
    """Deterministic, pure analysis of a channel's published-video history.

    `videos` is a sequence of (published_at, view_count) pairs. Each video's
    local weekday/hour is derived in `timezone` (default Asia/Dubai), then
    per-window medians/means are computed and ranked. Returns a PostingReport
    with the top `top_n` windows (each backed by at least `min_count`
    videos), weekday and hour aggregates, and a short advisory
    recommendation. Never raises for an empty history - that is a valid
    "not enough data yet" report."""
    if top_n < 1:
        raise PostingTimeError("top_n must be >= 1.")
    if min_count < 1:
        raise PostingTimeError("min_count must be >= 1.")

    windows: dict[tuple[int, int], list[int]] = defaultdict(list)
    for published_at, views in videos:
        local = published_at.astimezone(timezone)
        windows[(local.isoweekday(), local.hour)].append(views)

    ranked = [
        PostingWindow(
            weekday=weekday,
            hour=hour,
            count=len(view_list),
            median_views=_median(view_list),
            mean_views=statistics.mean(view_list),
        )
        for (weekday, hour), view_list in windows.items()
    ]
    best_windows = sorted(
        (window for window in ranked if window.count >= min_count),
        key=lambda w: (-w.median_views, -w.mean_views, w.weekday, w.hour),
    )[:top_n]

    weekday_map: dict[int, list[int]] = defaultdict(list)
    hour_map: dict[int, list[int]] = defaultdict(list)
    for (weekday, hour), view_list in windows.items():
        weekday_map[weekday].extend(view_list)
        hour_map[hour].extend(view_list)

    by_weekday = sorted(
        (
            WeekdayStat(weekday, len(view_list), _median(view_list), statistics.mean(view_list))
            for weekday, view_list in weekday_map.items()
        ),
        key=lambda stat: (-stat.median_views, -stat.mean_views, stat.weekday),
    )
    by_hour = sorted(
        (
            HourStat(hour, len(view_list), _median(view_list), statistics.mean(view_list))
            for hour, view_list in hour_map.items()
        ),
        key=lambda stat: (-stat.median_views, -stat.mean_views, stat.hour),
    )

    return PostingReport(
        generated_at=datetime.now(timezone),
        timezone=str(timezone),
        sample_count=len(videos),
        total_views=sum(views for _published_at, views in videos),
        best_windows=best_windows,
        by_weekday=by_weekday,
        by_hour=by_hour,
        recommendation=_build_recommendation(best_windows),
    )


def fetch_published_video_stats(settings: Settings) -> list[tuple[datetime, int]]:
    """Read-only fetch of the channel's current PUBLIC videos that have both
    a published timestamp and a view count, oldest first. A pure SELECT -
    never writes to any database. Private/unlisted uploads (which have no
    meaningful public view counts) and rows missing either field are
    excluded here, so the analysis only sees real performance data."""
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            """
            SELECT published_at, view_count
            FROM youtube_videos
            WHERE is_current = TRUE
              AND published_at IS NOT NULL
              AND view_count IS NOT NULL
              AND privacy_status = 'public'
            ORDER BY published_at ASC
            """
        ).fetchall()

    result: list[tuple[datetime, int]] = []
    for published_at, view_count in rows:
        if isinstance(published_at, datetime) and isinstance(view_count, int):
            result.append((published_at, view_count))
    return result


def build_posting_report(
    settings: Settings,
    *,
    timezone: Any = _DEFAULT_TIMEZONE,
    min_count: int = 1,
    top_n: int = 5,
) -> PostingReport:
    """Fetch the channel's published-video history and analyze it into a
    posting recommendation. Read-only end to end."""
    return analyze_posting_windows(
        fetch_published_video_stats(settings),
        timezone=timezone,
        min_count=min_count,
        top_n=top_n,
    )


def _median(values: list[int]) -> int:
    """Median of a non-empty list of ints (even-count medians averaged and
    rounded to a whole number)."""
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[mid]
    return round((sorted_values[mid - 1] + sorted_values[mid]) / 2)


def _build_recommendation(best_windows: list[PostingWindow]) -> str:
    if not best_windows:
        return (
            "Not enough published-video history yet to recommend a posting window. "
            "Run 'robin-engine youtube-sync' after publishing a few videos."
        )
    top = best_windows[0]
    if len(best_windows) == 1:
        return (
            f"Historically best window: {_format_window(top)} "
            f"(median {top.median_views} views)."
        )
    second = best_windows[1]
    return (
        f"Historically best windows: {_format_window(top)} and {_format_window(second)} "
        f"(top window median {top.median_views} views)."
    )


def _format_window(window: PostingWindow) -> str:
    return f"{WEEKDAY_NAMES[window.weekday - 1]} {window.hour:02d}:00"
