from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from .youtube_auth import YouTubeAuth

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


class YouTubeSyncError(RuntimeError):
    """Safe operator-facing failure while reading channel data from YouTube."""


@dataclass(frozen=True)
class YouTubeChannelSnapshot:
    channel_id: str
    title: str
    custom_url: str | None
    description: str
    published_at: datetime | None
    uploads_playlist_id: str
    view_count: int | None
    subscriber_count: int | None
    hidden_subscriber_count: bool
    video_count: int | None


@dataclass(frozen=True)
class YouTubeVideoSnapshot:
    video_id: str
    channel_id: str
    title: str
    description: str
    published_at: datetime | None
    duration_seconds: int | None
    privacy_status: str | None
    made_for_kids: bool | None
    self_declared_made_for_kids: bool | None
    category_id: str | None
    license: str | None
    tags: tuple[str, ...]
    thumbnail_url: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None


@dataclass(frozen=True)
class YouTubeSyncSnapshot:
    channel: YouTubeChannelSnapshot
    videos: tuple[YouTubeVideoSnapshot, ...]
    discovered_video_count: int


class YouTubeChannelSync:
    """Read-only YouTube channel inventory sync.

    Uses the OAuth credentials already managed by YouTubeAuth. It never opens
    a browser, uploads, edits, or publishes anything.
    """

    def __init__(self, auth: YouTubeAuth, expected_channel_id: str | None = None) -> None:
        self.auth = auth
        self.expected_channel_id = expected_channel_id.strip() if expected_channel_id else None

    def fetch_snapshot(self) -> YouTubeSyncSnapshot:
        credentials = self.auth.load_credentials()
        try:
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        except (HttpError, GoogleAuthError, OSError, TimeoutError) as exc:
            raise YouTubeSyncError(
                "YouTube channel sync could not initialize the API client."
            ) from exc

        channel_response = self._api_call(
            lambda: youtube.channels()
            .list(part="snippet,statistics,contentDetails,status", mine=True)
            .execute()
        )
        channel = self._parse_channel(channel_response)
        if self.expected_channel_id and channel.channel_id != self.expected_channel_id:
            raise YouTubeSyncError(
                "Authenticated YouTube channel does not match YOUTUBE_EXPECTED_CHANNEL_ID."
            )

        video_ids = self._fetch_upload_ids(youtube, channel.uploads_playlist_id)
        videos = self._fetch_videos(youtube, channel.channel_id, video_ids)
        return YouTubeSyncSnapshot(
            channel=channel,
            videos=tuple(videos),
            discovered_video_count=len(video_ids),
        )

    def _fetch_upload_ids(self, youtube: Any, uploads_playlist_id: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        page_token: str | None = None
        while True:
            response = self._api_call(
                lambda page_token=page_token: youtube.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                )
                .execute()
            )
            for item in self._items(response):
                details = item.get("contentDetails") or {}
                video_id = details.get("videoId")
                if isinstance(video_id, str) and video_id and video_id not in seen:
                    ids.append(video_id)
                    seen.add(video_id)
            next_token = response.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token
        return ids

    def _fetch_videos(
        self,
        youtube: Any,
        channel_id: str,
        video_ids: list[str],
    ) -> list[YouTubeVideoSnapshot]:
        videos: list[YouTubeVideoSnapshot] = []
        for batch in _chunks(video_ids, 50):
            response = self._api_call(
                lambda batch=batch: youtube.videos()
                .list(
                    part="snippet,statistics,contentDetails,status",
                    id=",".join(batch),
                    maxResults=50,
                )
                .execute()
            )
            for item in self._items(response):
                parsed = self._parse_video(item, channel_id)
                if parsed is not None:
                    videos.append(parsed)
        return videos

    @staticmethod
    def _api_call(call: Callable[[], Any]) -> dict[str, Any]:
        try:
            response = call()
        except (HttpError, GoogleAuthError, OSError, TimeoutError) as exc:
            raise YouTubeSyncError(
                "YouTube channel sync failed due to an API or transport error."
            ) from exc
        if not isinstance(response, dict):
            raise YouTubeSyncError("YouTube channel sync returned an invalid API response.")
        return cast(dict[str, Any], response)

    @staticmethod
    def _items(response: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = response.get("items") or []
        if not isinstance(raw_items, list):
            raise YouTubeSyncError("YouTube channel sync returned an invalid items payload.")
        return [cast(dict[str, Any], item) for item in raw_items if isinstance(item, dict)]

    def _parse_channel(self, response: dict[str, Any]) -> YouTubeChannelSnapshot:
        items = self._items(response)
        if not items:
            raise YouTubeSyncError("No YouTube channel was returned for these credentials.")
        item = items[0]
        channel_id = item.get("id")
        if not isinstance(channel_id, str) or not channel_id:
            raise YouTubeSyncError("YouTube channel response did not include a channel ID.")

        snippet = item.get("snippet") or {}
        statistics = item.get("statistics") or {}
        content_details = item.get("contentDetails") or {}
        related = content_details.get("relatedPlaylists") or {}
        uploads_playlist_id = related.get("uploads")
        if not isinstance(uploads_playlist_id, str) or not uploads_playlist_id:
            raise YouTubeSyncError("YouTube channel response did not include the uploads playlist.")

        title = snippet.get("title")
        return YouTubeChannelSnapshot(
            channel_id=channel_id,
            title=title if isinstance(title, str) else "",
            custom_url=_optional_str(snippet.get("customUrl")),
            description=_optional_str(snippet.get("description")) or "",
            published_at=_parse_datetime(snippet.get("publishedAt")),
            uploads_playlist_id=uploads_playlist_id,
            view_count=_parse_count(statistics.get("viewCount")),
            subscriber_count=_parse_count(statistics.get("subscriberCount")),
            hidden_subscriber_count=bool(statistics.get("hiddenSubscriberCount", False)),
            video_count=_parse_count(statistics.get("videoCount")),
        )

    @staticmethod
    def _parse_video(
        item: dict[str, Any], expected_channel_id: str
    ) -> YouTubeVideoSnapshot | None:
        video_id = item.get("id")
        if not isinstance(video_id, str) or not video_id:
            return None
        snippet = item.get("snippet") or {}
        item_channel_id = _optional_str(snippet.get("channelId"))
        if item_channel_id and item_channel_id != expected_channel_id:
            return None
        statistics = item.get("statistics") or {}
        content_details = item.get("contentDetails") or {}
        status = item.get("status") or {}
        raw_tags = snippet.get("tags") or []
        tags = (
            tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
            if isinstance(raw_tags, list)
            else ()
        )

        return YouTubeVideoSnapshot(
            video_id=video_id,
            channel_id=expected_channel_id,
            title=_optional_str(snippet.get("title")) or "",
            description=_optional_str(snippet.get("description")) or "",
            published_at=_parse_datetime(snippet.get("publishedAt")),
            duration_seconds=_parse_duration_seconds(content_details.get("duration")),
            privacy_status=_optional_str(status.get("privacyStatus")),
            made_for_kids=_optional_bool(status.get("madeForKids")),
            self_declared_made_for_kids=_optional_bool(status.get("selfDeclaredMadeForKids")),
            category_id=_optional_str(snippet.get("categoryId")),
            license=_optional_str(status.get("license")),
            tags=tags,
            thumbnail_url=_best_thumbnail(snippet.get("thumbnails")),
            view_count=_parse_count(statistics.get("viewCount")),
            like_count=_parse_count(statistics.get("likeCount")),
            comment_count=_parse_count(statistics.get("commentCount")),
        )


def _chunks(values: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _parse_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_duration_seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _best_thumbnail(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            url = candidate.get("url")
            if isinstance(url, str) and url:
                return url
    return None
