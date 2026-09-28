from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import token_store as ts  # noqa: E402
from robin_content_engine.device_auth import (  # noqa: E402
    DEVICE_GRANT_TYPE,
    DeviceAuthError,
    DeviceCode,
    poll_for_tokens,
    request_device_code,
)
from robin_content_engine.token_store import (  # noqa: E402
    StoredCredentials,
    TokenStoreError,
    decrypt_credentials,
    encrypt_credentials,
    fernet_from_service_account,
    materialize_token_file,
)
from robin_content_engine.youtube_auth import (  # noqa: E402
    YOUTUBE_MANAGE_SCOPE,
    YOUTUBE_READONLY_SCOPE,
    YouTubeAuth,
)

SA = {"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END"}
OTHER_SA = {"type": "service_account", "private_key": "-----BEGIN PRIVATE KEY-----\nxyz\n-----END"}
CHANNEL = "UCIcvbGsmSwMDXxjWXq4QG8A"
OAUTH_CLIENT = json.dumps({"installed": {"client_id": "c", "client_secret": "s"}})


def _stored(channel: str = CHANNEL) -> StoredCredentials:
    return StoredCredentials(
        client_id="cid.apps.googleusercontent.com",
        client_secret="csecret",
        refresh_token="1//refresh-secret",
        scopes=(YOUTUBE_MANAGE_SCOPE,),
        channel_id=channel,
    )


# ---------------------------------------------------------------------------
# token_store
# ---------------------------------------------------------------------------


def test_encrypt_round_trip_and_no_plaintext_in_ciphertext() -> None:
    fernet = fernet_from_service_account(SA)

    ciphertext = encrypt_credentials(fernet, _stored())

    assert "refresh-secret" not in ciphertext and "csecret" not in ciphertext
    assert decrypt_credentials(fernet_from_service_account(SA), ciphertext) == _stored()


def test_rotated_service_account_key_gives_clear_error() -> None:
    ciphertext = encrypt_credentials(fernet_from_service_account(SA), _stored())

    with pytest.raises(TokenStoreError, match="sign-in again"):
        decrypt_credentials(fernet_from_service_account(OTHER_SA), ciphertext)


def test_service_account_without_private_key_is_rejected() -> None:
    with pytest.raises(TokenStoreError, match="private_key"):
        fernet_from_service_account({"type": "service_account"})


def test_materialize_writes_0600_authorized_user_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ciphertext = encrypt_credentials(fernet_from_service_account(SA), _stored())
    monkeypatch.setattr(ts, "load_token", lambda url, name: ciphertext)
    dest = tmp_path / "secrets" / "token.json"

    creds = materialize_token_file("db", SA, dest, expected_channel_id=CHANNEL)

    assert creds.channel_id == CHANNEL
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    info = json.loads(dest.read_text())
    assert info["type"] == "authorized_user"
    assert info["refresh_token"] == "1//refresh-secret"
    assert info["scopes"] == [YOUTUBE_MANAGE_SCOPE]
    # The existing, unchanged uploader auth path accepts this file.
    loaded = YouTubeAuth(tmp_path / "unused.json", dest)._load_token()
    assert loaded is not None and loaded.refresh_token == "1//refresh-secret"


def test_materialize_refuses_other_channel_and_missing_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ciphertext = encrypt_credentials(fernet_from_service_account(SA), _stored("UCother"))
    monkeypatch.setattr(ts, "load_token", lambda url, name: ciphertext)
    with pytest.raises(TokenStoreError, match="different channel"):
        materialize_token_file("db", SA, tmp_path / "t.json", expected_channel_id=CHANNEL)
    assert not (tmp_path / "t.json").exists()

    monkeypatch.setattr(ts, "load_token", lambda url, name: None)
    with pytest.raises(TokenStoreError, match="No YouTube token"):
        materialize_token_file("db", SA, tmp_path / "t.json", expected_channel_id=CHANNEL)


# ---------------------------------------------------------------------------
# youtube_auth scope acceptance
# ---------------------------------------------------------------------------


def _token_file(tmp_path: Path, scopes: list[str]) -> Path:
    path = tmp_path / "token.json"
    path.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "c",
                "client_secret": "s",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": scopes,
            }
        )
    )
    return path


def test_full_youtube_scope_alone_is_accepted(tmp_path: Path) -> None:
    path = _token_file(tmp_path, [YOUTUBE_MANAGE_SCOPE])

    assert YouTubeAuth(tmp_path / "cs.json", path)._load_token() is not None


def test_readonly_scope_alone_is_still_rejected(tmp_path: Path) -> None:
    path = _token_file(tmp_path, [YOUTUBE_READONLY_SCOPE])

    assert YouTubeAuth(tmp_path / "cs.json", path)._load_token() is None


# ---------------------------------------------------------------------------
# device_auth
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class ScriptedPost:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, data: dict[str, Any], timeout: int) -> FakeResponse:
        self.calls.append((url, data))
        return self.responses.pop(0)


CODE = DeviceCode("dev-code", "ABCD-EFGH", "https://www.google.com/device", 600, 5)


def test_request_device_code_parses_response() -> None:
    post = ScriptedPost(
        [
            FakeResponse(
                200,
                {
                    "device_code": "d",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://www.google.com/device",
                    "expires_in": 1800,
                    "interval": 5,
                },
            )
        ]
    )

    code = request_device_code("cid", post=post)

    assert code.user_code == "ABCD-EFGH"
    assert post.calls[0][1]["scope"] == "https://www.googleapis.com/auth/youtube"


def test_request_device_code_explains_wrong_client_type() -> None:
    post = ScriptedPost([FakeResponse(401, {"error": "invalid_client"})])

    with pytest.raises(DeviceAuthError, match="TVs and Limited Input devices"):
        request_device_code("cid", post=post)


def test_poll_waits_through_pending_and_slow_down() -> None:
    post = ScriptedPost(
        [
            FakeResponse(428, {"error": "authorization_pending"}),
            FakeResponse(403, {"error": "slow_down"}),
            FakeResponse(
                200,
                {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "scope": "https://www.googleapis.com/auth/youtube",
                },
            ),
        ]
    )
    sleeps: list[float] = []

    tokens = poll_for_tokens("cid", "cs", CODE, post=post, sleep=sleeps.append, now=lambda: 0.0)

    assert tokens.refresh_token == "rt"
    assert tokens.scopes == ("https://www.googleapis.com/auth/youtube",)
    assert sleeps == [5, 5, 10]  # slow_down adds 5s
    assert post.calls[0][1]["grant_type"] == DEVICE_GRANT_TYPE


@pytest.mark.parametrize(
    ("error", "message"),
    [("access_denied", "declined"), ("expired_token", "expired"), ("invalid_grant", "rejected")],
)
def test_poll_terminal_errors(error: str, message: str) -> None:
    post = ScriptedPost([FakeResponse(400, {"error": error})])

    with pytest.raises(DeviceAuthError, match=message):
        poll_for_tokens("cid", "cs", CODE, post=post, sleep=lambda s: None, now=lambda: 0.0)


def test_poll_times_out_without_approval() -> None:
    clock = iter([0.0, 0.0, 700.0])
    post = ScriptedPost([FakeResponse(428, {"error": "authorization_pending"})])

    with pytest.raises(DeviceAuthError, match="expired"):
        poll_for_tokens(
            "cid", "cs", CODE, post=post, sleep=lambda s: None, now=lambda: next(clock)
        )


def test_approved_without_refresh_token_is_an_error() -> None:
    post = ScriptedPost([FakeResponse(200, {"access_token": "at"})])

    with pytest.raises(DeviceAuthError, match="no refresh token"):
        poll_for_tokens("cid", "cs", CODE, post=post, sleep=lambda s: None, now=lambda: 0.0)


# ---------------------------------------------------------------------------
# CLI: wrong channel is never stored
# ---------------------------------------------------------------------------


def test_device_auth_cli_refuses_wrong_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from robin_content_engine import cli as cli_module
    from robin_content_engine.cli import app as cli_app
    from robin_content_engine.device_auth import DeviceTokens
    from robin_content_engine.youtube_auth import ChannelIdentity

    saved: list[Any] = []
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_JSON", OAUTH_CLIENT)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(SA))
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda: SimpleNamespace(
            youtube_expected_channel_id=CHANNEL,
            database_url="db",
            youtube_client_secret_file=Path("cs.json"),
            youtube_token_file=Path("t.json"),
        ),
    )
    monkeypatch.setattr(cli_module, "request_device_code", lambda cid: CODE)
    monkeypatch.setattr(
        cli_module,
        "poll_for_tokens",
        lambda cid, cs, code: DeviceTokens("rt-secret", "at", (YOUTUBE_MANAGE_SCOPE,)),
    )
    monkeypatch.setattr(
        YouTubeAuth,
        "fetch_channel_identity",
        lambda self, creds: ChannelIdentity("UCsomeoneelse", "Other"),
    )
    monkeypatch.setattr(cli_module, "save_token", lambda *a: saved.append(a))

    result = CliRunner().invoke(cli_app, ["youtube-device-auth"])

    assert result.exit_code == 1
    assert "NOT the expected channel" in result.output
    assert saved == []
    assert "ABCD-EFGH" in result.output  # the user code IS shown
    assert "rt-secret" not in result.output  # the token never is


def test_device_auth_cli_stores_encrypted_token_for_right_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from robin_content_engine import cli as cli_module
    from robin_content_engine.cli import app as cli_app
    from robin_content_engine.device_auth import DeviceTokens
    from robin_content_engine.youtube_auth import ChannelIdentity

    saved: list[tuple[str, str, str]] = []
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_JSON", OAUTH_CLIENT)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(SA))
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda: SimpleNamespace(
            youtube_expected_channel_id=CHANNEL,
            database_url="db",
            youtube_client_secret_file=Path("cs.json"),
            youtube_token_file=Path("t.json"),
        ),
    )
    monkeypatch.setattr(cli_module, "request_device_code", lambda cid: CODE)
    monkeypatch.setattr(
        cli_module,
        "poll_for_tokens",
        lambda cid, cs, code: DeviceTokens("rt-secret", "at", (YOUTUBE_MANAGE_SCOPE,)),
    )
    monkeypatch.setattr(
        YouTubeAuth,
        "fetch_channel_identity",
        lambda self, creds: ChannelIdentity(CHANNEL, "Robinzo"),
    )
    monkeypatch.setattr(cli_module, "save_token", lambda *a: saved.append(a))

    result = CliRunner().invoke(cli_app, ["youtube-device-auth"])

    assert result.exit_code == 0, result.output
    assert "sign-in complete for 'Robinzo'" in result.output
    ((_url, name, ciphertext),) = saved
    assert name == "youtube" and "rt-secret" not in ciphertext
    assert decrypt_credentials(fernet_from_service_account(SA), ciphertext).channel_id == CHANNEL
