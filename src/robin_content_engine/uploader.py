import json
import random
import time
from pathlib import Path

import httplib2
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .models import GeneratedContent, UploadResult

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, OSError, TimeoutError)


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

    def _credentials(self) -> Credentials:
        credentials: Credentials | None = None
        if self.token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_file), [YOUTUBE_UPLOAD_SCOPE]
            )

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                credentials = None

        if not credentials or not credentials.valid:
            if not self.client_secret_file.is_file():
                raise FileNotFoundError(
                    f"YouTube OAuth client secret not found: {self.client_secret_file}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_file), [YOUTUBE_UPLOAD_SCOPE]
            )
            credentials = flow.run_local_server(port=0)

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def upload(self, video_path: Path, content: GeneratedContent) -> UploadResult:
        if not video_path.is_file():
            raise FileNotFoundError(f"Rendered video not found: {video_path}")

        youtube = build(
            "youtube",
            "v3",
            credentials=self._credentials(),
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
