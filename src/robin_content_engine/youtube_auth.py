from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_AUTH_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]


class AuthState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    NOT_AUTHENTICATED = "not_authenticated"
    AUTHENTICATED = "authenticated"
    REFRESH_FAILED = "refresh_failed"


class YouTubeAuthError(RuntimeError):
    """Raised for any YouTube authentication or channel-lookup failure.

    Messages are always operator-safe: never includes token, refresh_token,
    or client_secret values.
    """


@dataclass(frozen=True)
class ChannelIdentity:
    channel_id: str
    title: str
    custom_url: str | None = None


class YouTubeAuth:
    """Explicit, non-interactive-by-default YouTube OAuth service.

    Separates authentication (this class) from uploading (YouTubeUploader).
    Only `authorize_interactive()` ever opens a browser; every other method
    is safe to call unattended.
    """

    def __init__(self, client_secret_file: Path, token_file: Path) -> None:
        self.client_secret_file = client_secret_file
        self.token_file = token_file

    # ---- state -------------------------------------------------------

    def state(self) -> AuthState:
        """Report auth state without ever opening a browser."""
        credentials = self._load_token()
        if credentials is not None:
            if credentials.valid:
                return AuthState.AUTHENTICATED
            if credentials.expired and credentials.refresh_token:
                if self._try_refresh(credentials) is not None:
                    return AuthState.AUTHENTICATED
                return AuthState.REFRESH_FAILED
        if not self.client_secret_file.is_file():
            return AuthState.NOT_CONFIGURED
        return AuthState.NOT_AUTHENTICATED

    # ---- non-interactive credential loading ---------------------------

    def load_credentials(self) -> Credentials:
        """Load existing credentials, refreshing if needed. Never opens a browser."""
        credentials = self._load_token()
        if credentials is None:
            raise YouTubeAuthError(
                "YouTube is not authenticated. Run: robin-engine youtube-auth"
            )
        if credentials.valid:
            return credentials
        if credentials.expired and credentials.refresh_token:
            refreshed = self._try_refresh(credentials)
            if refreshed is not None:
                return refreshed
            raise YouTubeAuthError(
                "YouTube credential refresh failed. Run: robin-engine youtube-auth"
            )
        raise YouTubeAuthError(
            "YouTube is not authenticated. Run: robin-engine youtube-auth"
        )

    def _load_token(self) -> Credentials | None:
        if not self.token_file.is_file():
            return None
        try:
            raw = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        granted_scopes = set(raw.get("scopes") or [])
        if not set(YOUTUBE_AUTH_SCOPES).issubset(granted_scopes):
            return None
        try:
            return self._credentials_from_info(raw)
        except ValueError:
            return None

    @staticmethod
    def _credentials_from_info(info: dict[str, Any]) -> Credentials:
        return Credentials.from_authorized_user_info(info)  # type: ignore[no-untyped-call,no-any-return]

    def _try_refresh(self, credentials: Credentials) -> Credentials | None:
        """Attempt a token refresh. Covers both invalid-grant refresh failures
        (RefreshError) and network/transport failures (TransportError,
        TimeoutError, ...) since both share GoogleAuthError as their base."""
        try:
            credentials.refresh(Request())  # type: ignore[no-untyped-call]
        except GoogleAuthError:
            return None
        self._persist(credentials)
        return credentials

    def _persist(self, credentials: Credentials) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(credentials.to_json(), encoding="utf-8")  # type: ignore[no-untyped-call]

    # ---- interactive authorization -------------------------------------

    def authorize_interactive(self) -> Credentials:
        """Run the system-browser localhost OAuth flow and persist the result."""
        if not self.client_secret_file.is_file():
            raise YouTubeAuthError(
                f"YouTube OAuth client secret not found: {self.client_secret_file}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_file), YOUTUBE_AUTH_SCOPES
        )
        credentials: Credentials = flow.run_local_server(port=0)
        self._persist(credentials)
        return credentials

    # ---- channel lookup --------------------------------------------------

    def fetch_channel_identity(self, credentials: Credentials) -> ChannelIdentity:
        """Non-interactive authenticated-channel lookup via channels().list(mine=True)."""
        try:
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            response = youtube.channels().list(part="snippet", mine=True).execute()
        except (HttpError, GoogleAuthError) as exc:
            raise YouTubeAuthError(
                "YouTube channel lookup failed due to an API or transport error."
            ) from exc
        items = response.get("items") or []
        if not items:
            raise YouTubeAuthError("No YouTube channel found for these credentials.")
        channel_id = items[0].get("id")
        if not channel_id:
            raise YouTubeAuthError("YouTube channel response did not include a channel ID.")
        snippet = items[0].get("snippet") or {}
        return ChannelIdentity(
            channel_id=channel_id,
            title=snippet.get("title", ""),
            custom_url=snippet.get("customUrl"),
        )

    # ---- convenience entry points for the CLI -----------------------------

    def authenticate_and_verify(self) -> ChannelIdentity:
        """Interactive: run OAuth, then verify the resulting channel."""
        credentials = self.authorize_interactive()
        return self.fetch_channel_identity(credentials)

    def verify_current_channel(self) -> ChannelIdentity:
        """Non-interactive: load existing credentials, then verify the channel."""
        credentials = self.load_credentials()
        return self.fetch_channel_identity(credentials)
