import json
import random
import time
from pathlib import Path

import httplib2  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from googleapiclient.http import MediaFileUpload  # type: ignore[import-untyped]

from .models import GeneratedContent, UploadResult
from .youtube_auth import YouTubeAuth, YouTubeAuthError

RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, OSError, TimeoutError)


class UploadNotAuthenticatedError(RuntimeError):
    """Raised when an unattended upload is attempted without valid YouTube credentials."""


class YouTubeUploader:
    def __init__(
        self,
        client_secret_file: Path,
        token_file: Path,
        privacy_status: str,
        category_id: str,
    ) -> None:
        self.client_secret_file = client_secret_file
        self.token_file = token_file
        self.privacy_status = privacy_status
        self.category_id = category_id
        self._auth = YouTubeAuth(client_secret_file, token_file)

    def upload(self, video_path: Path, content: GeneratedContent) -> UploadResult:
        if not video_path.is_file():
            raise FileNotFoundError(f"Rendered video not found: {video_path}")

        try:
            credentials = self._auth.load_credentials()
        except YouTubeAuthError as exc:
            raise UploadNotAuthenticatedError(
                "YouTube is not authenticated for unattended upload. "
                "Run: robin-engine youtube-auth"
            ) from exc

        youtube = build(
            "youtube",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": content.title,
                    "description": content.description,
                    "tags": content.tags,
                    "categoryId": self.category_id,
                },
                "status": {
                    "privacyStatus": self.privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            },
            media_body=MediaFileUpload(
                str(video_path),
                chunksize=8 * 1024 * 1024,
                resumable=True,
            ),
        )

        response = None
        retry = 0
        while response is None:
            try:
                _, response = request.next_chunk()
            except HttpError as exc:
                if exc.resp.status not in RETRIABLE_STATUS_CODES:
                    raise
                retry += 1
                self._sleep_before_retry(retry, str(exc))
            except RETRIABLE_EXCEPTIONS as exc:
                retry += 1
                self._sleep_before_retry(retry, str(exc))

        youtube_id = response.get("id") if isinstance(response, dict) else None
        if not youtube_id:
            raise RuntimeError(
                "YouTube upload returned no video ID: "
                + json.dumps(response, ensure_ascii=False, default=str)[:1000]
            )
        return UploadResult(
            youtube_id=youtube_id,
            privacy_status=self.privacy_status,
        )

    @staticmethod
    def _sleep_before_retry(retry: int, reason: str) -> None:
        if retry > 8:
            raise RuntimeError(f"YouTube upload retry limit exceeded: {reason}")
        time.sleep(random.uniform(0, min(2**retry, 64)))
