from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from google.auth.exceptions import TransportError  # noqa: E402

from robin_content_engine import youtube_sync as ys  # noqa: E402
from robin_content_engine.youtube_sync import (  # noqa: E402
    YouTubeChannelSync,
    YouTubeSyncError,
    _parse_duration_seconds,
)


class FakeAuth:
    def __init__(self, credentials: object | None = None) -> None:
        self.credentials = credentials or object()
        self.calls = 0

    def load_credentials(self) -> object:
        self.calls += 1
        return self.credentials


class FakeRequest:
    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error

    def execute(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.response


class FakeResource:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeRequest:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("No fake response left for API call")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            return FakeRequest(error=value)
        return FakeRequest(response=value)


class FakeYouTubeClient:
    def __init__(
        self,
        *,
        channels: list[dict[str, Any] | Exception],
        playlist_items: list[dict[str, Any] | Exception],
        videos: list[dict[str, Any] | Exception],
    ) -> None:
        self.channels_resource = FakeResource(channels)
        self.playlist_items_resource = FakeResource(playlist_items)
        self.videos_resource = FakeResource(videos)

    def channels(self) -> FakeResource:
        return self.channels_resource

    def playlistItems(self) -> FakeResource:  # noqa: N802
        return self.playlist_items_resource

    def videos(self) -> FakeResource:
        return self.videos_resource


def _channel_response(channel_id: str = "UC123") -> dict[str, Any]:
    return {
        "items": [
            {
                "id": channel_id,
                "snippet": {
                    "title": "Robin",
                    "customUrl": "@roben.1",
                    "description": "Gaming channel",
                    "publishedAt": "2013-02-05T00:00:00Z",
                },
                "statistics": {
                    "viewCount": "2678",
                    "subscriberCount": "18",
                    "hiddenSubscriberCount": False,
                    "videoCount": "122",
                },
                "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
                "status": {"privacyStatus": "public"},
            }
        ]
    }


def _video(video_id: str, *, duration: str = "PT1M2S") -> dict[str, Any]:
    return {
        "id": video_id,
        "snippet": {
            "channelId": "UC123",
            "title": f"Video {video_id}",
            "description": "description",
            "publishedAt": "2026-08-01T10:00:00Z",
            "categoryId": "20",
            "tags": ["fortnite", "gaming"],
            "thumbnails": {
                "default": {"url": "https://example.test/default.jpg"},
                "high": {"url": "https://example.test/high.jpg"},
            },
        },
        "statistics": {"viewCount": "100", "likeCount": "12", "commentCount": "3"},
        "contentDetails": {"duration": duration},
        "status": {
            "privacyStatus": "public",
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
            "license": "youtube",
        },
    }


def test_fetch_snapshot_paginates_uploads_and_parses_video_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeYouTubeClient(
        channels=[_channel_response()],
        playlist_items=[
            {
                "items": [
                    {"contentDetails": {"videoId": "v1"}},
                    {"contentDetails": {"videoId": "v2"}},
                ],
                "nextPageToken": "NEXT",
            },
            {"items": [{"contentDetails": {"videoId": "v3"}}]},
        ],
        videos=[{"items": [_video("v1"), _video("v2", duration="PT45S"), _video("v3")]}],
    )
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    auth = FakeAuth()
    service = YouTubeChannelSync(auth, expected_channel_id="UC123")  # type: ignore[arg-type]
    snapshot = service.fetch_snapshot()

    assert auth.calls == 1
    assert snapshot.channel.channel_id == "UC123"
    assert snapshot.channel.title == "Robin"
    assert snapshot.channel.uploads_playlist_id == "UU123"
    assert snapshot.channel.view_count == 2678
    assert snapshot.channel.subscriber_count == 18
    assert snapshot.discovered_video_count == 3
    assert [video.video_id for video in snapshot.videos] == ["v1", "v2", "v3"]
    assert snapshot.videos[0].duration_seconds == 62
    assert snapshot.videos[1].duration_seconds == 45
    assert snapshot.videos[0].thumbnail_url == "https://example.test/high.jpg"
    assert snapshot.videos[0].tags == ("fortnite", "gaming")
    assert snapshot.videos[0].view_count == 100
    assert snapshot.videos[0].made_for_kids is False
    assert snapshot.videos[0].self_declared_made_for_kids is False

    assert client.channels_resource.calls == [
        {"part": "snippet,statistics,contentDetails,status", "mine": True}
    ]
    assert client.playlist_items_resource.calls[0]["pageToken"] is None
    assert client.playlist_items_resource.calls[1]["pageToken"] == "NEXT"
    assert client.videos_resource.calls[0]["id"] == "v1,v2,v3"


def test_fetch_snapshot_deduplicates_playlist_video_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeYouTubeClient(
        channels=[_channel_response()],
        playlist_items=[
            {
                "items": [
                    {"contentDetails": {"videoId": "v1"}},
                    {"contentDetails": {"videoId": "v1"}},
                ]
            }
        ],
        videos=[{"items": [_video("v1")]}],
    )
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    snapshot = YouTubeChannelSync(FakeAuth()).fetch_snapshot()  # type: ignore[arg-type]

    assert snapshot.discovered_video_count == 1
    assert len(snapshot.videos) == 1
    assert client.videos_resource.calls[0]["id"] == "v1"


def test_fetch_snapshot_batches_video_lookup_at_fifty(monkeypatch: pytest.MonkeyPatch) -> None:
    video_ids = [f"v{index}" for index in range(51)]
    client = FakeYouTubeClient(
        channels=[_channel_response()],
        playlist_items=[
            {"items": [{"contentDetails": {"videoId": video_id}} for video_id in video_ids]}
        ],
        videos=[
            {"items": [_video(video_id) for video_id in video_ids[:50]]},
            {"items": [_video(video_ids[50])]},
        ],
    )
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    snapshot = YouTubeChannelSync(FakeAuth()).fetch_snapshot()  # type: ignore[arg-type]

    assert snapshot.discovered_video_count == 51
    assert len(snapshot.videos) == 51
    assert len(client.videos_resource.calls) == 2
    assert len(client.videos_resource.calls[0]["id"].split(",")) == 50
    assert client.videos_resource.calls[1]["id"] == "v50"


def test_expected_channel_id_mismatch_stops_before_playlist_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeYouTubeClient(
        channels=[_channel_response("UC-WRONG")],
        playlist_items=[],
        videos=[],
    )
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    with pytest.raises(YouTubeSyncError, match="YOUTUBE_EXPECTED_CHANNEL_ID"):
        YouTubeChannelSync(FakeAuth(), expected_channel_id="UC123").fetch_snapshot()  # type: ignore[arg-type]

    assert client.playlist_items_resource.calls == []
    assert client.videos_resource.calls == []


def test_transport_error_is_normalized_without_raw_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-echo-this-transport-detail"
    client = FakeYouTubeClient(
        channels=[TransportError(secret)],
        playlist_items=[],
        videos=[],
    )
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    with pytest.raises(YouTubeSyncError) as exc_info:
        YouTubeChannelSync(FakeAuth()).fetch_snapshot()  # type: ignore[arg-type]

    assert secret not in str(exc_info.value)
    assert "API or transport error" in str(exc_info.value)


def test_missing_uploads_playlist_is_safe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _channel_response()
    response["items"][0]["contentDetails"] = {"relatedPlaylists": {}}
    client = FakeYouTubeClient(channels=[response], playlist_items=[], videos=[])
    monkeypatch.setattr(ys, "build", lambda *args, **kwargs: client)

    with pytest.raises(YouTubeSyncError, match="uploads playlist"):
        YouTubeChannelSync(FakeAuth()).fetch_snapshot()  # type: ignore[arg-type]


def test_parse_duration_seconds() -> None:
    assert _parse_duration_seconds("PT58S") == 58
    assert _parse_duration_seconds("PT1H2M3S") == 3723
    assert _parse_duration_seconds("P1DT2H") == 93600
    assert _parse_duration_seconds("not-a-duration") is None
    assert _parse_duration_seconds(None) is None
