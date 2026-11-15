"""Targeted archived Shorts use existing Drive/Neon/YouTube pipeline safely."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import psycopg  # noqa: E402
import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli  # noqa: E402
from robin_content_engine.drive_runner import ChannelVideo, GameEvidence  # noqa: E402

TARGET_1 = "MrZkqujTwdg"
TARGET_2 = "knFnj6dQURg"
TARGET_ARCHIVE = "4GY0WKVLhuY"


class FakeConnection:
    def __init__(
        self, rows: list[tuple[str, bool | None]], fallback_audience: bool | None = None
    ) -> None:
        self.rows = rows
        self.fallback_audience = fallback_audience

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object) -> FakeConnection:
        assert "made_for_kids" in query
        if "ANY(%s)" in query:
            assert set(params[0]) == {TARGET_1, TARGET_2, TARGET_ARCHIVE}  # type: ignore[index]
        else:
            assert params == ("other123456",)
        return self

    def fetchall(self) -> list[tuple[str, bool | None]]:
        return self.rows

    def fetchone(self) -> tuple[bool | None]:
        return (self.fallback_audience,)


@pytest.fixture
def setup_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    monkeypatch.setenv("DRIVE_TAKEOUT_FOLDER_ID", "drive-folder")
    monkeypatch.setenv("DRIVE_TARGET_SOURCE_VIDEO_IDS", f"{TARGET_1},{TARGET_2},{TARGET_ARCHIVE}")
    settings = SimpleNamespace(database_url="db", youtube_max_uploads_per_day=3)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "db_upload_allowed", lambda _settings: True)
    monkeypatch.setattr(cli, "build_drive_service", lambda _json: object())
    monkeypatch.setattr(
        cli,
        "fetch_channel_videos",
        lambda _settings: [
            ChannelVideo(TARGET_1, "Ggg", 6017, ("#PS5Live", "Fortnite")),
            ChannelVideo(TARGET_2, "Ggg", 1935, ("#PS5Live", "Fortnite")),
            ChannelVideo(TARGET_ARCHIVE, "Archived Gameplay Clip", 633, ("archive", "gameplay")),
            ChannelVideo("other123456", "Unrelated", 300, ()),
        ],
    )
    monkeypatch.setattr(
        psycopg, "connect",
        lambda _db: FakeConnection([(TARGET_1, True), (TARGET_2, True), (TARGET_ARCHIVE, True)]),
    )
    calls: dict[str, Any] = {"selections": [], "published": []}
    result = SimpleNamespace(
        job_id=501,
        video_id=TARGET_1,
        game="Fortnite",
        evidence=GameEvidence.CONFIRMED,
        source_title="Fortnite gameplay",
        rank=1,
        start_seconds=50.0,
        end_seconds=70.0,
        production=SimpleNamespace(final_video_path=tmp_path / "result.mp4"),
    )

    def fake_produce(_settings: Any, _service: Any, _folder: str, **kwargs: Any) -> Any:
        videos = kwargs.get("channel_videos")
        calls["selections"].append(None if videos is None else [v.video_id for v in videos])
        return result

    def fake_publish(
        _result: Any, _settings: Any, _execute: bool, *, made_for_kids: bool | None = None
    ) -> None:
        calls["published"].append(made_for_kids)

    monkeypatch.setattr(cli, "produce_next_short", fake_produce)
    monkeypatch.setattr(cli, "_publish_drive_short", fake_publish)
    calls["result"] = result
    return calls


def test_targeted_archive_selects_exact_ids_and_preserves_kids_setting(
    setup_target: dict[str, Any],
) -> None:
    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])

    assert outcome.exit_code == 0, outcome.output
    assert setup_target["selections"] == [[TARGET_1, TARGET_2, TARGET_ARCHIVE]]
    assert setup_target["published"] == [True]



def test_owner_archived_gameplay_source_retains_kids_setting(
    setup_target: dict[str, Any],
) -> None:
    """A non-Fortnite owned archive can be the selected target safely."""
    result = setup_target["result"]
    result.video_id = TARGET_ARCHIVE
    result.game = None
    result.evidence = GameEvidence.NONE
    result.source_title = "Archived gameplay"

    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])

    assert outcome.exit_code == 0, outcome.output
    assert setup_target["selections"] == [[TARGET_1, TARGET_2, TARGET_ARCHIVE]]
    assert setup_target["published"] == [True]
    assert f"from {TARGET_ARCHIVE}" in outcome.output


def test_targeted_archive_uses_existing_rotation_when_target_exhausted(
    setup_target: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_produce(_settings: Any, _service: Any, _folder: str, **kwargs: Any) -> None:
        videos = kwargs.get("channel_videos")
        setup_target["selections"].append(None if videos is None else [v.video_id for v in videos])
        return None

    monkeypatch.setattr(cli, "produce_next_short", fake_produce)
    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])
    assert outcome.exit_code == 0, outcome.output
    assert setup_target["selections"] == [[TARGET_1, TARGET_2, TARGET_ARCHIVE], None]
    assert setup_target["published"] == []


def test_targeted_archive_refuses_unknown_audience(
    setup_target: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        psycopg, "connect",
        lambda _db: FakeConnection([(TARGET_1, True), (TARGET_2, True), (TARGET_ARCHIVE, None)]),
    )
    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])
    assert outcome.exit_code == 1
    assert "audience setting missing" in outcome.output
    assert setup_target["selections"] == []
    assert setup_target["published"] == []


def test_fallback_upload_uses_actual_source_audience(
    setup_target: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback must not silently upload an existing kids video as non-kids."""
    setup_target["result"].video_id = "other123456"
    monkeypatch.setattr(
        psycopg, "connect",
        lambda _db: FakeConnection([(TARGET_1, True), (TARGET_2, True)], True),
    )

    def fake_produce(_settings: Any, _service: Any, _folder: str, **kwargs: Any) -> Any:
        chosen = kwargs.get("channel_videos")
        setup_target["selections"].append(None if chosen is None else [v.video_id for v in chosen])
        return None if chosen is not None else setup_target["result"]

    monkeypatch.setattr(cli, "produce_next_short", fake_produce)
    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])
    assert outcome.exit_code == 0, outcome.output
    assert setup_target["selections"] == [[TARGET_1, TARGET_2, TARGET_ARCHIVE], None]
    assert setup_target["published"] == [True]


def test_fallback_refuses_unknown_source_audience(
    setup_target: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_target["result"].video_id = "other123456"

    def fake_produce(_settings: Any, _service: Any, _folder: str, **kwargs: Any) -> Any:
        return None if kwargs.get("channel_videos") is not None else setup_target["result"]

    monkeypatch.setattr(cli, "produce_next_short", fake_produce)
    outcome = CliRunner().invoke(cli.app, ["drive-produce", "--execute-private-upload"])
    assert outcome.exit_code == 1
    assert "audience is unknown" in outcome.output
    assert setup_target["published"] == []
