from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robin_content_engine.channel_repository import ChannelRepository  # noqa: E402
from robin_content_engine.youtube_sync import (  # noqa: E402
    YouTubeChannelSnapshot,
    YouTubeSyncSnapshot,
    YouTubeVideoSnapshot,
)


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    @contextmanager
    def transaction(self):
        yield


class FakePool:
    def __init__(self) -> None:
        self.conn = FakeConnection()

    @contextmanager
    def connection(self):
        yield self.conn


def _snapshot() -> YouTubeSyncSnapshot:
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)
    channel = YouTubeChannelSnapshot(
        channel_id="UC123",
        title="Robin",
        custom_url="@roben.1",
        description="Gaming",
        published_at=now,
        uploads_playlist_id="UU123",
        view_count=2678,
        subscriber_count=18,
        hidden_subscriber_count=False,
        video_count=2,
    )
    videos = tuple(
        YouTubeVideoSnapshot(
            video_id=f"v{index}",
            channel_id="UC123",
            title=f"Video {index}",
            description="desc",
            published_at=now,
            duration_seconds=58,
            privacy_status="public",
            made_for_kids=False,
            self_declared_made_for_kids=False,
            category_id="20",
            license="youtube",
            tags=("fortnite", "gaming"),
            thumbnail_url="https://example.test/thumb.jpg",
            view_count=100,
            like_count=10,
            comment_count=2,
        )
        for index in range(2)
    )
    return YouTubeSyncSnapshot(channel=channel, videos=videos, discovered_video_count=2)


def test_save_snapshot_upserts_channel_reconciles_current_videos_and_upserts_each_video() -> None:
    repository = ChannelRepository("postgresql://fake")
    fake_pool = FakePool()
    repository.pool = fake_pool  # type: ignore[assignment]

    stored = repository.save_snapshot(_snapshot())

    assert stored == 2
    assert len(fake_pool.conn.executed) == 4

    channel_sql, channel_params = fake_pool.conn.executed[0]
    assert "INSERT INTO youtube_channels" in channel_sql
    assert "ON CONFLICT (channel_id) DO UPDATE" in channel_sql
    assert channel_params[0] == "UC123"

    reconcile_sql, reconcile_params = fake_pool.conn.executed[1]
    normalized_reconcile = " ".join(reconcile_sql.split())
    assert "SET is_current = FALSE" in normalized_reconcile
    assert "channel_id = %s AND is_current = TRUE" in normalized_reconcile
    assert reconcile_params == ("UC123",)

    video_sql, video_params = fake_pool.conn.executed[2]
    assert "INSERT INTO youtube_videos" in video_sql
    assert "ON CONFLICT (video_id) DO UPDATE" in video_sql
    assert "is_current = TRUE" in video_sql
    assert video_params[0] == "v0"
    assert video_params[1] == "UC123"
    assert video_params[11] == '["fortnite", "gaming"]'
