from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.posting_time import (  # noqa: E402
    PostingReport,
    PostingTimeError,
    analyze_posting_windows,
    build_posting_report,
    fetch_published_video_stats,
)

_DUBAI = ZoneInfo("Asia/Dubai")


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.executed.append((sql, params))
        return self

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConn:
    def __init__(self, rows: list[Any]) -> None:
        self.cursor = FakeCursor(rows)

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        return self.cursor.execute(sql, params)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(database_url="postgresql://fake")


def _report(
    *,
    videos: list[tuple[datetime, int]] | None = None,
    min_count: int = 1,
    top_n: int = 5,
    timezone: Any = _DUBAI,
) -> PostingReport:
    return analyze_posting_windows(
        videos or [], timezone=timezone, min_count=min_count, top_n=top_n
    )


# ---------------------------------------------------------------------------
# Pure analysis
# ---------------------------------------------------------------------------


def test_empty_history_returns_insufficient_report() -> None:
    report = _report(videos=[])

    assert report.sample_count == 0
    assert report.total_views == 0
    assert report.best_windows == []
    assert report.by_weekday == []
    assert report.by_hour == []
    assert "Not enough published-video history" in report.recommendation


def test_ranks_windows_by_median_views() -> None:
    # Saturday 20:00 UAE: two videos with 100 and 300 views -> median 200.
    # Friday 21:00 UAE: three videos with 50, 60, 70 views -> median 60.
    videos = [
        # 2026-08-15 is a Saturday.
        (_utc(2026, 8, 15, 16, 0), 100),  # 16:00 UTC = 20:00 Dubai
        (_utc(2026, 8, 15, 16, 30), 300),
        # 2026-08-14 is a Friday.
        (_utc(2026, 8, 14, 17, 0), 50),  # 17:00 UTC = 21:00 Dubai
        (_utc(2026, 8, 14, 17, 15), 60),
        (_utc(2026, 8, 14, 17, 30), 70),
    ]

    report = _report(videos=videos)

    assert report.sample_count == 5
    top = report.best_windows[0]
    assert (top.weekday, top.hour) == (6, 20)  # Saturday 20:00
    assert top.median_views == 200
    assert top.count == 2
    assert report.best_windows[1].median_views == 60
    assert "Saturday 20:00" in report.recommendation


def test_median_of_even_count_is_averaged() -> None:
    videos = [
        (_utc(2026, 8, 15, 16, 0), 10),
        (_utc(2026, 8, 15, 16, 10), 30),
        (_utc(2026, 8, 15, 16, 20), 50),
        (_utc(2026, 8, 15, 16, 30), 90),
    ]

    report = _report(videos=videos)

    assert report.best_windows[0].median_views == 40  # (30 + 50) / 2


def test_min_count_filters_underrepresented_windows() -> None:
    videos = [
        # Single sample in one window with a high outlier view count.
        (_utc(2026, 8, 15, 16, 0), 900),
        # Two samples in another window.
        (_utc(2026, 8, 14, 17, 0), 100),
        (_utc(2026, 8, 14, 17, 30), 110),
    ]

    noisy = _report(videos=videos, min_count=1)
    assert noisy.best_windows[0].median_views == 900

    conservative = _report(videos=videos, min_count=2)
    assert all(window.count >= 2 for window in conservative.best_windows)
    assert conservative.best_windows[0].median_views == 105


def test_top_n_limits_best_windows() -> None:
    videos = [
        (_utc(2026, 8, 15, hour, 0), 100 + hour) for hour in range(0, 10)
    ]

    report = _report(videos=videos, top_n=3)

    assert len(report.best_windows) == 3


def test_timezone_shift_buckets_in_local_time() -> None:
    # 2026-08-15 23:30 UTC = 2026-08-16 03:30 Dubai (next day, Sunday 03:00).
    report = _report(videos=[(_utc(2026, 8, 15, 23, 30), 42)])

    window = report.best_windows[0]
    assert (window.weekday, window.hour) == (7, 3)  # Sunday 03:00


def test_weekday_and_hour_aggregates() -> None:
    videos = [
        (_utc(2026, 8, 15, 16, 0), 100),  # Saturday 20:00
        (_utc(2026, 8, 15, 17, 0), 300),  # Saturday 21:00
        (_utc(2026, 8, 14, 17, 0), 100),  # Friday 21:00
    ]

    report = _report(videos=videos)

    assert report.by_weekday[0].weekday == 6  # Saturday highest median
    assert report.by_weekday[0].count == 2
    assert report.by_weekday[0].median_views == 200
    assert report.by_hour[0].hour == 21  # 21:00 highest median across days
    assert report.by_hour[0].count == 2
    assert report.by_hour[0].median_views == 200


def test_invalid_parameters_raise() -> None:
    with pytest.raises(PostingTimeError, match="top_n"):
        _report(videos=[(_utc(2026, 8, 15, 16, 0), 1)], top_n=0)
    with pytest.raises(PostingTimeError, match="min_count"):
        _report(videos=[(_utc(2026, 8, 15, 16, 0), 1)], min_count=0)


# ---------------------------------------------------------------------------
# Read-only DB fetch
# ---------------------------------------------------------------------------


def test_fetch_published_video_stats_returns_public_videos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import robin_content_engine.posting_time as pt

    dt1 = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
    dt2 = datetime(2026, 8, 14, 17, 0, tzinfo=UTC)
    rows = [(dt1, 100), (dt2, 200)]
    fake_conn = FakeConn(rows)
    monkeypatch.setattr(pt.psycopg, "connect", lambda url: fake_conn)

    stats = fetch_published_video_stats(_settings())

    assert stats == [(dt1, 100), (dt2, 200)]
    # The query is a read-only SELECT restricted to current public videos
    # with both a published timestamp and a view count.
    sql = fake_conn.cursor.executed[0][0]
    assert sql.strip().startswith("SELECT")
    assert "FROM youtube_videos" in sql
    assert "is_current = TRUE" in sql
    assert "published_at IS NOT NULL" in sql
    assert "view_count IS NOT NULL" in sql
    assert "privacy_status = 'public'" in sql


def test_build_posting_report_is_read_only_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import robin_content_engine.posting_time as pt

    dt = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
    monkeypatch.setattr(pt.psycopg, "connect", lambda url: FakeConn([(dt, 123)]))

    report = build_posting_report(_settings())

    assert report.sample_count == 1
    assert report.total_views == 123
    assert report.best_windows[0].median_views == 123


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fake_report() -> PostingReport:
    return analyze_posting_windows(
        [
            (datetime(2026, 8, 15, 16, 0, tzinfo=UTC), 100),
            (datetime(2026, 8, 15, 16, 30, tzinfo=UTC), 300),
            (datetime(2026, 8, 14, 17, 0, tzinfo=UTC), 50),
        ],
        timezone=_DUBAI,
    )


def test_posting_report_cli_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "build_posting_report", lambda settings, **kw: _fake_report())
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["posting-report"])

    assert result.exit_code == 0
    assert "Best windows (median views)" in result.output
    assert "Saturday 20:00" in result.output
    assert "Recommendation:" in result.output


def test_posting_report_cli_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "build_posting_report", lambda settings, **kw: _fake_report())
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["posting-report", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["sample_count"] == 3
    assert payload["best_windows"][0]["weekday"] == 6
    assert payload["best_windows"][0]["hour"] == 20


def test_posting_report_cli_rejects_unknown_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["posting-report", "--timezone", "Not/AZone"])

    assert result.exit_code != 0
    assert "Unknown IANA timezone" in result.output
