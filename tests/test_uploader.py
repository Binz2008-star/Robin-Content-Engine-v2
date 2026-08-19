from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import uploader as uploader_module  # noqa: E402
from robin_content_engine import youtube_auth as ya  # noqa: E402
from robin_content_engine.models import GeneratedContent  # noqa: E402
from robin_content_engine.uploader import UploadNotAuthenticatedError, YouTubeUploader  # noqa: E402
from robin_content_engine.youtube_auth import YouTubeAuth  # noqa: E402


class ExplodingFlow:
    """Canary: raises if interactive OAuth is ever entered during an unattended upload."""

    @classmethod
    def from_client_secrets_file(cls, filename: str, scopes: list[str]) -> Any:
        raise AssertionError("Uploader must never start interactive OAuth implicitly.")


class FakeUploadRequest:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def next_chunk(self) -> tuple[None, dict[str, Any]]:
        return None, self._response


class FakeVideosResource:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.insert_calls: list[dict[str, Any]] = []

    def insert(self, **kwargs: Any) -> FakeUploadRequest:
        self.insert_calls.append(kwargs)
        return FakeUploadRequest(self._response)


class FakeYouTubeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.videos_resource = FakeVideosResource(response)

    def videos(self) -> FakeVideosResource:
        return self.videos_resource


def _content() -> GeneratedContent:
    return GeneratedContent(
        title="A Valid Smoke Test Title",
        description="A sufficiently long description for model validation purposes.",
        tags=["tag1", "tag2"],
        script="A script that is definitely long enough to pass the model's validation checks.",
    )


def test_upload_fails_clearly_when_not_authenticated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Canary: if the uploader ever falls back to interactive OAuth, this blows up the test.
    monkeypatch.setattr(ya, "InstalledAppFlow", ExplodingFlow)

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video-bytes")

    uploader = YouTubeUploader(
        client_secret_file=tmp_path / "client_secret.json",
        token_file=tmp_path / "token.json",  # missing: not authenticated
        privacy_status="private",
        category_id="20",
    )

    with pytest.raises(UploadNotAuthenticatedError, match="youtube-auth"):
        uploader.upload(video, _content())


def test_upload_never_calls_authorize_interactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[None] = []
    monkeypatch.setattr(
        YouTubeAuth, "authorize_interactive", lambda self: calls.append(None) or object()
    )

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video-bytes")
    uploader = YouTubeUploader(
        client_secret_file=tmp_path / "client_secret.json",
        token_file=tmp_path / "token.json",
        privacy_status="private",
        category_id="20",
    )

    with pytest.raises(UploadNotAuthenticatedError):
        uploader.upload(video, _content())

    assert calls == []


def test_upload_missing_video_file_fails_before_auth_check(tmp_path: Path) -> None:
    uploader = YouTubeUploader(
        client_secret_file=tmp_path / "client_secret.json",
        token_file=tmp_path / "token.json",
        privacy_status="private",
        category_id="20",
    )
    with pytest.raises(FileNotFoundError):
        uploader.upload(tmp_path / "does-not-exist.mp4", _content())


def test_upload_preserves_privacy_category_and_kids_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video-bytes")

    response = {"id": "yt1234567"}
    client_holder: dict[str, FakeYouTubeClient] = {}

    def fake_build(*args: Any, **kwargs: Any) -> FakeYouTubeClient:
        client = FakeYouTubeClient(response)
        client_holder["client"] = client
        return client

    monkeypatch.setattr(uploader_module, "build", fake_build)
    monkeypatch.setattr(YouTubeAuth, "load_credentials", lambda self: object())

    uploader = YouTubeUploader(
        client_secret_file=tmp_path / "client_secret.json",
        token_file=tmp_path / "token.json",
        privacy_status="private",
        category_id="20",
    )
    result = uploader.upload(video, _content())

    assert result.youtube_id == "yt1234567"
    assert result.privacy_status == "private"
    insert_kwargs = client_holder["client"].videos_resource.insert_calls[0]
    assert insert_kwargs["body"]["status"]["privacyStatus"] == "private"
    assert insert_kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False
    assert insert_kwargs["body"]["snippet"]["categoryId"] == "20"
