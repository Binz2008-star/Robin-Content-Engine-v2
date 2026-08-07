from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from .youtube_sync import YouTubeSyncSnapshot


class ChannelRepository:
    """Persistence boundary for read-only YouTube channel snapshots."""

    def __init__(self, database_url: str) -> None:
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=3,
            open=False,
        )

    def open(self) -> None:
        self.pool.open(wait=True)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def running(self) -> Iterator["ChannelRepository"]:
        self.open()
        try:
            yield self
        finally:
            self.close()

    def save_snapshot(self, snapshot: YouTubeSyncSnapshot) -> int:
        channel = snapshot.channel
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO youtube_channels (
                    channel_id,
                    title,
                    custom_url,
                    description,
                    published_at,
                    uploads_playlist_id,
                    view_count,
                    subscriber_count,
                    hidden_subscriber_count,
                    video_count,
                    last_synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (channel_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    custom_url = EXCLUDED.custom_url,
                    description = EXCLUDED.description,
                    published_at = EXCLUDED.published_at,
                    uploads_playlist_id = EXCLUDED.uploads_playlist_id,
                    view_count = EXCLUDED.view_count,
                    subscriber_count = EXCLUDED.subscriber_count,
                    hidden_subscriber_count = EXCLUDED.hidden_subscriber_count,
                    video_count = EXCLUDED.video_count,
                    last_synced_at = NOW()
                """,
                (
                    channel.channel_id,
                    channel.title,
                    channel.custom_url,
                    channel.description,
                    channel.published_at,
                    channel.uploads_playlist_id,
                    channel.view_count,
                    channel.subscriber_count,
                    channel.hidden_subscriber_count,
                    channel.video_count,
                ),
            )

            conn.execute(
                """
                UPDATE youtube_videos
                SET is_current = FALSE
                WHERE channel_id = %s AND is_current = TRUE
                """,
                (channel.channel_id,),
            )

            for video in snapshot.videos:
                conn.execute(
                    """
                    INSERT INTO youtube_videos (
                        video_id,
                        channel_id,
                        title,
                        description,
                        published_at,
                        duration_seconds,
                        privacy_status,
                        made_for_kids,
                        self_declared_made_for_kids,
                        category_id,
                        license,
                        tags,
                        thumbnail_url,
                        view_count,
                        like_count,
                        comment_count,
                        is_current,
                        last_synced_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s, %s, %s, %s, TRUE, NOW()
                    )
                    ON CONFLICT (video_id) DO UPDATE SET
                        channel_id = EXCLUDED.channel_id,
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        published_at = EXCLUDED.published_at,
                        duration_seconds = EXCLUDED.duration_seconds,
                        privacy_status = EXCLUDED.privacy_status,
                        made_for_kids = EXCLUDED.made_for_kids,
                        self_declared_made_for_kids = EXCLUDED.self_declared_made_for_kids,
                        category_id = EXCLUDED.category_id,
                        license = EXCLUDED.license,
                        tags = EXCLUDED.tags,
                        thumbnail_url = EXCLUDED.thumbnail_url,
                        view_count = EXCLUDED.view_count,
                        like_count = EXCLUDED.like_count,
                        comment_count = EXCLUDED.comment_count,
                        is_current = TRUE,
                        last_synced_at = NOW()
                    """,
                    (
                        video.video_id,
                        video.channel_id,
                        video.title,
                        video.description,
                        video.published_at,
                        video.duration_seconds,
                        video.privacy_status,
                        video.made_for_kids,
                        video.self_declared_made_for_kids,
                        video.category_id,
                        video.license,
                        json.dumps(video.tags, ensure_ascii=False),
                        video.thumbnail_url,
                        video.view_count,
                        video.like_count,
                        video.comment_count,
                    ),
                )

        return len(snapshot.videos)
