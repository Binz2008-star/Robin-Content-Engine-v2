from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.game_performance import (  # noqa: E402
    UNCLASSIFIED,
    GamePerformanceError,
    GamePerformanceReport,
    VideoStat,
    analyze_game_performance,
    build_game_performance_report,
    classify_game,
    fetch_video_stats,
)


def _video(
    views: int,
    *,
    title: str = "",
    source_title: str | None = None,
    tags: tuple[str, ...] = (),
    duration: int | None = 30,
    likes: int | None = None,
    engine: bool = False,
    video_id: str = "vid",
) -> VideoStat:
    return VideoStat(
        video_id=video_id,
        title=title,
        source_title=source_title,
        tags=tags,
        duration_seconds=duration,
        view_count=views,
        like_count=likes,
        produced_by_engine=engine,
    )


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


# ---------------------------------------------------------------------------
# Game classification
# ---------------------------------------------------------------------------


def test_classify_prefers_engine_source_title_over_ai_title() -> None:
    # AI metadata may rewrite the title in Arabic with no game name; the
    # engine's original capture title still identifies the game.
    video = _video(10, title="لقطة أسطورية", source_title="Apex Legends gameplay")

    assert classify_game(video) == "Apex Legends"


def test_classify_falls_back_to_title_then_tags() -> None:
    assert classify_game(_video(1, title="Fortnite victory royale")) == "Fortnite"
    assert classify_game(_video(1, title="Clutch 1v3", tags=("roblox", "shorts"))) == "Roblox"


def test_classify_never_guesses_ambiguous_capture_names() -> None:
    # A bare "Black ops" capture name has proven unreliable (it was Apex);
    # detect_game refuses it, so the video stays unclassified.
    assert classify_game(_video(1, title="Black ops")) == UNCLASSIFIED
    assert classify_game(_video(1, title="")) == UNCLASSIFIED


# ---------------------------------------------------------------------------
# Pure analysis
# ---------------------------------------------------------------------------


def test_empty_history_returns_insufficient_report() -> None:
    report = analyze_game_performance([])

    assert report.sample_count == 0
    assert report.total_views == 0
    assert report.by_game == []
    assert "Not enough classified public-video history" in report.recommendation


def test_ranks_games_by_median_views() -> None:
    videos = [
        _video(100, title="Fortnite a"),
        _video(300, title="Fortnite b"),  # Fortnite median 200
        _video(50, title="Apex a"),
        _video(60, title="Apex b"),
        _video(5000, title="Apex c"),  # Apex median 60 despite one outlier
    ]

    report = analyze_game_performance(videos)

    assert [stat.game for stat in report.by_game] == ["Fortnite", "Apex Legends"]
    assert report.by_game[0].median_views == 200
    assert report.by_game[1].median_views == 60
    assert report.by_game[1].mean_views == pytest.approx(1703.33, rel=1e-3)
    assert report.sample_count == 5
    assert report.total_views == 5510
    assert "Fortnite performs best" in report.recommendation
    assert "ahead of Apex Legends" in report.recommendation


def test_unclassified_always_sorts_last_and_is_never_recommended() -> None:
    videos = [
        _video(9000, title="Black ops"),  # huge but unclassifiable
        _video(10, title="Roblox obby"),
    ]

    report = analyze_game_performance(videos)

    assert [stat.game for stat in report.by_game] == ["Roblox", UNCLASSIFIED]
    assert UNCLASSIFIED not in report.recommendation
    assert "Only one game has history so far: Roblox" in report.recommendation


def test_small_sample_recommendation_is_hedged() -> None:
    few = analyze_game_performance(
        [_video(100, title="Fortnite"), _video(10, title="Apex")]
    )
    many = analyze_game_performance(
        [_video(100 + i, title="Fortnite", video_id=f"f{i}") for i in range(5)]
        + [_video(10, title="Apex")]
    )

    assert "Small sample" in few.recommendation
    assert "Small sample" not in many.recommendation


def test_engine_count_and_like_rate() -> None:
    videos = [
        _video(100, title="Fortnite", likes=10, engine=True),
        _video(300, title="Fortnite", likes=None, engine=False),
        _video(100, title="Fortnite", likes=5, engine=True),
    ]

    stat = analyze_game_performance(videos).by_game[0]

    assert stat.count == 3
    assert stat.engine_count == 2
    assert stat.median_likes == 8  # median of [5, 10] = 7.5 -> 8
    # Like rate only counts videos that report likes: 15 / 200.
    assert stat.like_rate == pytest.approx(0.075)


def test_like_fields_are_none_when_no_video_reports_likes() -> None:
    stat = analyze_game_performance([_video(100, title="Fortnite")]).by_game[0]

    assert stat.median_likes is None
    assert stat.like_rate is None


def test_format_filter_splits_shorts_and_long_form() -> None:
    videos = [
        _video(100, title="Fortnite short", duration=45),
        _video(200, title="Fortnite edge", duration=180),  # still a Short
        _video(900, title="Fortnite long", duration=1200),
        _video(999, title="Fortnite unknown", duration=None),
    ]

    shorts = analyze_game_performance(videos, video_format="short")
    long_form = analyze_game_performance(videos, video_format="long")
    everything = analyze_game_performance(videos, video_format="all")

    assert shorts.sample_count == 2
    assert long_form.sample_count == 1
    # Unknown durations only appear in the unfiltered view.
    assert everything.sample_count == 4


def test_min_count_hides_thin_games() -> None:
    videos = [
        _video(900, title="Roblox"),
        _video(100, title="Fortnite"),
        _video(110, title="Fortnite"),
    ]

    report = analyze_game_performance(videos, min_count=2)

    assert [stat.game for stat in report.by_game] == ["Fortnite"]


def test_invalid_parameters_raise() -> None:
    with pytest.raises(GamePerformanceError, match="min_count"):
        analyze_game_performance([], min_count=0)
    with pytest.raises(GamePerformanceError, match="video_format"):
        analyze_game_performance([], video_format="vertical")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Read-only DB fetch
# ---------------------------------------------------------------------------


def test_fetch_video_stats_is_a_read_only_public_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import robin_content_engine.game_performance as gp

    rows = [
        ("a1", "Apex clip", "Apex Legends gameplay", ["apex"], 40, 120, 9, True),
        ("b2", "Other", None, None, None, 7, None, False),
        ("c3", "Bad row", None, [], 30, None, None, False),  # no view count
    ]
    fake_conn = FakeConn(rows)
    monkeypatch.setattr(gp.psycopg, "connect", lambda url: fake_conn)

    stats = fetch_video_stats(_settings())

    assert [s.video_id for s in stats] == ["a1", "b2"]
    assert stats[0].source_title == "Apex Legends gameplay"
    assert stats[0].tags == ("apex",)
    assert stats[0].produced_by_engine is True
    assert stats[1].tags == ()
    assert stats[1].duration_seconds is None
    assert stats[1].like_count is None
    assert stats[1].produced_by_engine is False

    sql = fake_conn.cursor.executed[0][0]
    assert sql.strip().startswith("SELECT")
    for forbidden in ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP"):
        assert forbidden not in sql.upper()
    assert "FROM youtube_videos" in sql
    assert "LEFT JOIN video_queue" in sql
    assert "is_current = TRUE" in sql
    assert "view_count IS NOT NULL" in sql
    assert "privacy_status = 'public'" in sql


def test_build_report_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    import robin_content_engine.game_performance as gp

    rows = [("a1", "Fortnite win", None, [], 30, 123, None, False)]
    monkeypatch.setattr(gp.psycopg, "connect", lambda url: FakeConn(rows))

    report = build_game_performance_report(_settings())

    assert report.sample_count == 1
    assert report.by_game[0].game == "Fortnite"
    assert report.by_game[0].median_views == 123


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fake_report() -> GamePerformanceReport:
    return analyze_game_performance(
        [
            _video(100, title="Fortnite", likes=10, engine=True),
            _video(300, title="Fortnite"),
            _video(50, title="Apex"),
            _video(80, title="Black ops"),
        ]
    )


def test_game_report_cli_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module, "build_game_performance_report", lambda settings, **kw: _fake_report()
    )
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["game-report"])

    assert result.exit_code == 0, result.output
    assert "By game (median views):" in result.output
    assert "#1  Fortnite - 2 video(s) (1 by engine), median 200" in result.output
    assert "#2  Apex Legends" in result.output
    assert f"  -  {UNCLASSIFIED}" in result.output
    assert "Recommendation: Fortnite performs best" in result.output


def test_game_report_cli_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module, "build_game_performance_report", lambda settings, **kw: _fake_report()
    )
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["game-report", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sample_count"] == 4
    assert payload["by_game"][0]["game"] == "Fortnite"
    assert payload["by_game"][0]["engine_count"] == 1


def test_game_report_cli_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_build(settings: Any, **kwargs: Any) -> GamePerformanceReport:
        seen.update(kwargs)
        return _fake_report()

    monkeypatch.setattr(cli_module, "build_game_performance_report", fake_build)
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["game-report", "--format", "short", "--min-count", "3"])

    assert result.exit_code == 0, result.output
    assert seen == {"video_format": "short", "min_count": 3}


def test_game_report_cli_rejects_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "Settings", lambda: SimpleNamespace(database_url="x"))

    result = CliRunner().invoke(cli_app, ["game-report", "--format", "vertical"])

    assert result.exit_code != 0
    assert "--format must be one of" in result.output
