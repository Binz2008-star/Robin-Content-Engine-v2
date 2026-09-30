"""One-time, phone-friendly YouTube sign-in (OAuth 2.0 device flow).

Replaces the localhost browser flow that needed the retired PC: the runner
shows a short code and a URL; the owner opens google.com/device on any
phone, enters the code, picks the channel account and allows access. The
runner polls Google until that happens, verifies the authorized account IS
the expected channel, and only then stores the refresh token (encrypted,
see token_store). Nothing here prints token material - only the public
verification URL and user code, which are meant to be shown.

Device flow only allows a small set of scopes; the full YouTube scope
(which includes uploading and reading) is one of them, so that is what is
requested. If Google rejects it, the flow fails with a clear error and
nothing is stored.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
DEVICE_FLOW_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/youtube",)

_TIMEOUT_SECONDS = 20


class DeviceAuthError(RuntimeError):
    """Operator-safe messages only - never includes secrets or tokens."""


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class DeviceTokens:
    refresh_token: str
    access_token: str
    scopes: tuple[str, ...]


PostFn = Callable[..., Any]


def request_device_code(
    client_id: str, *, scopes: tuple[str, ...] = DEVICE_FLOW_SCOPES, post: PostFn = requests.post
) -> DeviceCode:
    response = post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": " ".join(scopes)},
        timeout=_TIMEOUT_SECONDS,
    )
    body = _json(response)
    if response.status_code != 200:
        raise DeviceAuthError(
            f"Google refused the sign-in request: {body.get('error', response.status_code)} "
            f"({body.get('error_description', 'no description')}). The OAuth client must be of "
            "type 'TVs and Limited Input devices'."
        )
    try:
        return DeviceCode(
            device_code=str(body["device_code"]),
            user_code=str(body["user_code"]),
            verification_url=str(body.get("verification_url") or body["verification_uri"]),
            expires_in=int(body["expires_in"]),
            interval=int(body.get("interval", 5)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeviceAuthError("Unexpected response from Google's device-code endpoint.") from exc


def poll_for_tokens(
    client_id: str,
    client_secret: str,
    code: DeviceCode,
    *,
    post: PostFn = requests.post,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> DeviceTokens:
    """Poll until the owner approves, denies, or the code expires."""
    deadline = now() + code.expires_in
    interval = max(1, code.interval)
    while now() < deadline:
        sleep(interval)
        response = post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": code.device_code,
                "grant_type": DEVICE_GRANT_TYPE,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        body = _json(response)
        if response.status_code == 200:
            refresh_token = body.get("refresh_token")
            if not refresh_token:
                raise DeviceAuthError(
                    "Google approved the sign-in but returned no refresh token; revoke the "
                    "app's access in the Google account and sign in again."
                )
            return DeviceTokens(
                refresh_token=str(refresh_token),
                access_token=str(body.get("access_token", "")),
                scopes=tuple(str(body.get("scope", "")).split()),
            )
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise DeviceAuthError("The sign-in was declined on the phone. Nothing was stored.")
        if error == "expired_token":
            break
        raise DeviceAuthError(f"Google rejected the sign-in: {error or response.status_code}.")
    raise DeviceAuthError("The sign-in code expired before it was approved. Start again.")


def _json(response: Any) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
