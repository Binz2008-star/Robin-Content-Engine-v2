from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from google.auth.exceptions import RefreshError, TransportError  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine import youtube_auth as ya  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.youtube_auth import (  # noqa: E402
    YOUTUBE_AUTH_SCOPES,
    YOUTUBE_READONLY_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
    AuthState,
    ChannelIdentity,
    YouTubeAuth,
    YouTubeAuthError,
)

FUTURE_EXPIRY = "2999-01-01T00:00:00Z"
PAST_EXPIRY = "2000-01-01T00:00:00Z"
SECRET_SENTINEL = "sentinel-refresh-token-do-not-print-me"


def _write_token(
    path: Path,
    *,
    expiry: str | None = FUTURE_EXPIRY,
    scopes: list[str] | None = None,
    refresh_token: str = SECRET_SENTINEL,
    client_id: str = "test-client-id",
    client_secret: str = "test-client-secret",
) -> None:
    data: dict[str, Any] = {
        "token": "test-access-token",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": YOUTUBE_AUTH_SCOPES if scopes is None else scopes,
    }
    if expiry is not None:
        data["expiry"] = expiry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class ExplodingFlow:
    """Canary: raises if the interactive OAuth flow is ever entered unexpectedly."""

    @classmethod
    def from_client_secrets_file(cls, filename: str, scopes: list[str]) -> Any:
        raise AssertionError("Interactive OAuth flow must not run here.")


class FakeFlow:
    def __init__(self, credentials: Any) -> None:
        self._credentials = credentials
        self.run_local_server_calls: list[int] = []

    def run_local_server(self, port: int = 0) -> Any:
        self.run_local_server_calls.append(port)
        return self._credentials


class FakeFlowFactory:
    def __init__(self, credentials: Any) -> None:
        self.credentials = credentials
        self.flow: FakeFlow | None = None
        self.calls: list[tuple[str, list[str]]] = []

    def from_client_secrets_file(self, filename: str, scopes: list[str]) -> FakeFlow:
        self.calls.append((filename, scopes))
        self.flow = FakeFlow(self.credentials)
        return self.flow


class FakeCredentials:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_json(self) -> str:
        return json.dumps(self._payload)


class FakeExecutable:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def execute(self) -> dict[str, Any]:
        return self._response


class FakeChannelsResource:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeExecutable:
        self.list_calls.append(kwargs)
        return FakeExecutable(self._response)


class FakeYouTubeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.channels_resource = FakeChannelsResource(response)

    def channels(self) -> FakeChannelsResource:
        return self.channels_resource


def _fake_build(response: dict[str, Any]) -> Any:
    client = FakeYouTubeClient(response)

    def build(*args: Any, **kwargs: Any) -> FakeYouTubeClient:
        return client

    return build, client


# ---------------------------------------------------------------------------
# state()
# ---------------------------------------------------------------------------


def test_status_missing_token_is_not_authenticated_no_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ya, "InstalledAppFlow", ExplodingFlow)
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
    token = tmp_path / "token.json"  # does not exist

    auth = YouTubeAuth(client_secret, token)
    assert auth.state() == AuthState.NOT_AUTHENTICATED


def test_status_not_configured_when_client_secret_and_token_missing(tmp_path: Path) -> None:
    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    assert auth.state() == AuthState.NOT_CONFIGURED


def test_status_valid_token_is_authenticated(tmp_path: Path) -> None:
    token = tmp_path / "token.json"
    _write_token(token, expiry=FUTURE_EXPIRY)
    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    assert auth.state() == AuthState.AUTHENTICATED


def test_status_expired_token_with_refresh_token_refreshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY)
    calls: list[Any] = []

    def fake_refresh(self: Credentials, request: Any) -> None:
        calls.append(request)
        self.token = "refreshed-access-token"
        self.expiry = None  # None means "never expires" per google-auth semantics

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    before = token.read_text(encoding="utf-8")
    assert auth.state() == AuthState.AUTHENTICATED
    assert len(calls) == 1
    after = token.read_text(encoding="utf-8")
    assert after != before  # refreshed credentials were persisted


def test_status_refresh_failure_is_safe_auth_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY)

    def fake_refresh(self: Credentials, request: Any) -> None:
        raise RefreshError("refresh denied")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    assert auth.state() == AuthState.REFRESH_FAILED

    with pytest.raises(YouTubeAuthError):
        auth.load_credentials()


def test_status_transport_failure_during_refresh_is_refresh_failed_no_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: a network/transport error during refresh (e.g. DNS failure,
    # connection reset) is a GoogleAuthError subclass distinct from
    # RefreshError. state() must treat it the same way: refresh_failed, never
    # an unhandled exception, and it must never fall back to opening a browser.
    monkeypatch.setattr(ya, "InstalledAppFlow", ExplodingFlow)
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY, refresh_token=SECRET_SENTINEL)

    def fake_refresh(self: Credentials, request: Any) -> None:
        raise TransportError("connection reset by peer")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    assert auth.state() == AuthState.REFRESH_FAILED


def test_load_credentials_transport_failure_raises_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY, refresh_token=SECRET_SENTINEL)

    def fake_refresh(self: Credentials, request: Any) -> None:
        raise TransportError("connection reset by peer")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    with pytest.raises(YouTubeAuthError, match="credential refresh failed") as exc_info:
        auth.load_credentials()

    assert SECRET_SENTINEL not in str(exc_info.value)


def test_status_requires_both_scopes(tmp_path: Path) -> None:
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
    token = tmp_path / "token.json"
    _write_token(token, expiry=FUTURE_EXPIRY, scopes=[YOUTUBE_UPLOAD_SCOPE])  # missing readonly
    auth = YouTubeAuth(client_secret, token)
    assert auth.state() == AuthState.NOT_AUTHENTICATED


# ---------------------------------------------------------------------------
# authorize_interactive()
# ---------------------------------------------------------------------------


def test_authorize_interactive_missing_client_secret_fails_explicitly(tmp_path: Path) -> None:
    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    with pytest.raises(YouTubeAuthError, match="client secret not found"):
        auth.authorize_interactive()


def test_authorize_interactive_invokes_installed_app_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
    token = tmp_path / "nested" / "token.json"

    fake_credentials = FakeCredentials({"refresh_token": SECRET_SENTINEL, "token": "at"})
    factory = FakeFlowFactory(fake_credentials)
    monkeypatch.setattr(ya, "InstalledAppFlow", factory)

    auth = YouTubeAuth(client_secret, token)
    result = auth.authorize_interactive()

    assert result is fake_credentials
    assert factory.calls == [(str(client_secret), YOUTUBE_AUTH_SCOPES)]
    assert factory.flow is not None
    assert factory.flow.run_local_server_calls == [0]


def test_authorize_interactive_requests_both_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
    factory = FakeFlowFactory(FakeCredentials({"token": "at"}))
    monkeypatch.setattr(ya, "InstalledAppFlow", factory)

    auth = YouTubeAuth(client_secret, tmp_path / "token.json")
    auth.authorize_interactive()

    requested_scopes = factory.calls[0][1]
    assert YOUTUBE_UPLOAD_SCOPE in requested_scopes
    assert YOUTUBE_READONLY_SCOPE in requested_scopes


def test_authorize_interactive_persists_token_and_creates_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")
    token = tmp_path / "does" / "not" / "exist" / "token.json"
    assert not token.parent.exists()

    payload = {"refresh_token": SECRET_SENTINEL, "token": "at"}
    factory = FakeFlowFactory(FakeCredentials(payload))
    monkeypatch.setattr(ya, "InstalledAppFlow", factory)

    auth = YouTubeAuth(client_secret, token)
    auth.authorize_interactive()

    assert token.is_file()
    assert json.loads(token.read_text(encoding="utf-8")) == payload


# ---------------------------------------------------------------------------
# fetch_channel_identity()
# ---------------------------------------------------------------------------


def test_fetch_channel_identity_uses_mine_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = {
        "items": [{"id": "UC123", "snippet": {"title": "My Channel", "customUrl": "@mychannel"}}]
    }
    build_fn, client = _fake_build(response)
    monkeypatch.setattr(ya, "build", build_fn)

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]

    assert client.channels_resource.list_calls == [{"part": "snippet", "mine": True}]


def test_fetch_channel_identity_parses_id_and_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = {
        "items": [{"id": "UC123", "snippet": {"title": "My Channel", "customUrl": "@mychannel"}}]
    }
    build_fn, _ = _fake_build(response)
    monkeypatch.setattr(ya, "build", build_fn)

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    identity = auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]

    assert identity == ChannelIdentity(
        channel_id="UC123", title="My Channel", custom_url="@mychannel"
    )


def test_fetch_channel_identity_no_channel_raises_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_fn, _ = _fake_build({"items": []})
    monkeypatch.setattr(ya, "build", build_fn)

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    with pytest.raises(YouTubeAuthError, match="No YouTube channel"):
        auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]


SAFE_CHANNEL_LOOKUP_MESSAGE = "YouTube channel lookup failed due to an API or transport error."
RAW_TRANSPORT_DETAIL = "raw-transport-detail-must-not-leak-to-operator"


class RaisingExecutable:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def execute(self) -> dict[str, Any]:
        raise self._exc


class RaisingChannelsResource:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def list(self, **kwargs: Any) -> RaisingExecutable:
        return RaisingExecutable(self._exc)


class RaisingYouTubeClient:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def channels(self) -> RaisingChannelsResource:
        return RaisingChannelsResource(self._exc)


def test_fetch_channel_identity_execute_transport_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ya, "build", lambda *a, **kw: RaisingYouTubeClient(TransportError(RAW_TRANSPORT_DETAIL))
    )

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    with pytest.raises(YouTubeAuthError) as exc_info:
        auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]

    assert str(exc_info.value) == SAFE_CHANNEL_LOOKUP_MESSAGE
    assert RAW_TRANSPORT_DETAIL not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None  # `raise ... from exc` preserved internally


def test_fetch_channel_identity_execute_http_error_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    http_error = HttpError(
        resp=type("Resp", (), {"status": 500, "reason": "Internal Server Error"})(),
        content=b"raw body detail",
    )
    monkeypatch.setattr(ya, "build", lambda *a, **kw: RaisingYouTubeClient(http_error))

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    with pytest.raises(YouTubeAuthError) as exc_info:
        auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]

    assert str(exc_info.value) == SAFE_CHANNEL_LOOKUP_MESSAGE
    assert b"raw body detail" not in str(exc_info.value).encode()


def test_fetch_channel_identity_build_transport_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: build() itself (API discovery) used to run outside the try
    # block, so a transport failure there would escape as a raw exception.
    def raising_build(*args: Any, **kwargs: Any) -> Any:
        raise TransportError(RAW_TRANSPORT_DETAIL)

    monkeypatch.setattr(ya, "build", raising_build)

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    with pytest.raises(YouTubeAuthError) as exc_info:
        auth.fetch_channel_identity(FakeCredentials({}))  # type: ignore[arg-type]

    assert str(exc_info.value) == SAFE_CHANNEL_LOOKUP_MESSAGE
    assert RAW_TRANSPORT_DETAIL not in str(exc_info.value)


# ---------------------------------------------------------------------------
# secrecy
# ---------------------------------------------------------------------------


def test_no_secrets_in_error_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY, refresh_token=SECRET_SENTINEL)

    def fake_refresh(self: Credentials, request: Any) -> None:
        raise RefreshError("refresh denied")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    auth = YouTubeAuth(tmp_path / "client_secret.json", token)
    with pytest.raises(YouTubeAuthError) as exc_info:
        auth.load_credentials()

    assert SECRET_SENTINEL not in str(exc_info.value)


def test_no_secrets_in_channel_lookup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_fn, _ = _fake_build({"items": []})
    monkeypatch.setattr(ya, "build", build_fn)

    auth = YouTubeAuth(tmp_path / "client_secret.json", tmp_path / "token.json")
    fake_creds = FakeCredentials({"refresh_token": SECRET_SENTINEL})
    with pytest.raises(YouTubeAuthError) as exc_info:
        auth.fetch_channel_identity(fake_creds)  # type: ignore[arg-type]

    assert SECRET_SENTINEL not in str(exc_info.value)


# ---------------------------------------------------------------------------
# CLI commands (robin-engine youtube-auth / youtube-status)
# ---------------------------------------------------------------------------


class FakeSettings:
    def __init__(self) -> None:
        self.youtube_client_secret_file = Path("client_secret.json")
        self.youtube_token_file = Path("token.json")


class FakeAuthAuthenticated:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def authenticate_and_verify(self) -> ChannelIdentity:
        return ChannelIdentity(channel_id="UC999", title="Robin Channel", custom_url="@robin")

    def state(self) -> AuthState:
        return AuthState.AUTHENTICATED

    def verify_current_channel(self) -> ChannelIdentity:
        return ChannelIdentity(channel_id="UC999", title="Robin Channel", custom_url=None)


class FakeAuthNotAuthenticated:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def state(self) -> AuthState:
        return AuthState.NOT_AUTHENTICATED

    def authenticate_and_verify(self) -> ChannelIdentity:
        raise AssertionError("youtube-status must never trigger interactive auth")

    def verify_current_channel(self) -> ChannelIdentity:
        raise AssertionError("youtube-status must not verify channel when not authenticated")


class FakeAuthRefreshFailed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def state(self) -> AuthState:
        return AuthState.REFRESH_FAILED

    def verify_current_channel(self) -> ChannelIdentity:
        raise AssertionError("verify_current_channel should not run when state != AUTHENTICATED")


class FakeAuthChannelVerificationFails:
    """Auth succeeds, but the channel-lookup call itself fails (API/transport error)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def state(self) -> AuthState:
        return AuthState.AUTHENTICATED

    def verify_current_channel(self) -> ChannelIdentity:
        raise YouTubeAuthError(SAFE_CHANNEL_LOOKUP_MESSAGE)


def test_cli_youtube_auth_prints_only_safe_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuthAuthenticated)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-auth"])

    assert result.exit_code == 0
    assert "YouTube authentication successful." in result.output
    assert "Robin Channel" in result.output
    assert "UC999" in result.output
    assert "@robin" in result.output
    assert SECRET_SENTINEL not in result.output


def test_cli_youtube_status_not_authenticated_never_opens_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuthNotAuthenticated)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-status"])

    assert result.exit_code == 0
    assert AuthState.NOT_AUTHENTICATED.value in result.output
    assert "robin-engine youtube-auth" in result.output


def test_cli_youtube_status_authenticated_prints_safe_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuthAuthenticated)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-status"])

    assert result.exit_code == 0
    assert "Robin Channel" in result.output
    assert "UC999" in result.output


def test_cli_youtube_status_refresh_failed_tells_operator_to_reauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuthRefreshFailed)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-status"])

    assert result.exit_code == 0
    assert "robin-engine youtube-auth" in result.output


def test_cli_youtube_status_transport_refresh_failure_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end through the REAL YouTubeAuth (not the fakes above): a
    # network/transport failure during refresh must surface as a clean,
    # no-traceback CLI result telling the operator to re-auth - never a
    # crash, and never a leaked secret.
    token = tmp_path / "token.json"
    _write_token(token, expiry=PAST_EXPIRY, refresh_token=SECRET_SENTINEL)
    client_secret = tmp_path / "client_secret.json"

    class RealSettings:
        def __init__(self) -> None:
            self.youtube_client_secret_file = client_secret
            self.youtube_token_file = token

    def fake_refresh(self: Credentials, request: Any) -> None:
        raise TransportError("connection reset by peer")

    monkeypatch.setattr(cli_module, "Settings", RealSettings)
    monkeypatch.setattr(ya, "InstalledAppFlow", ExplodingFlow)
    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-status"])

    assert result.exit_code == 0
    assert result.exception is None
    assert AuthState.REFRESH_FAILED.value in result.output
    assert "robin-engine youtube-auth" in result.output
    assert SECRET_SENTINEL not in result.output


def test_cli_youtube_status_channel_verification_failure_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuthChannelVerificationFails)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["youtube-status"])

    assert result.exit_code == 0
    assert result.exception is None
    assert SAFE_CHANNEL_LOOKUP_MESSAGE in result.output
    assert "robin-engine youtube-auth" in result.output
    assert RAW_TRANSPORT_DETAIL not in result.output
    assert SECRET_SENTINEL not in result.output
