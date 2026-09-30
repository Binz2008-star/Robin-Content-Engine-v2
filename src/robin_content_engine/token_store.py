"""Encrypted YouTube OAuth token storage in the engine's own database.

The PC that held token.json is gone and GitHub runners are ephemeral, so the
long-lived refresh token from the one-time phone sign-in lives in the
`oauth_tokens` table - ENCRYPTED. The key is derived (HKDF-SHA256) from the
Drive service-account private key the runner already receives as a secret,
so the owner does not have to create or paste a second secret. Consequence:
rotating the service-account key makes the stored token unreadable and the
owner simply signs in once more (a clear error says so).

At run time `materialize_token_file()` writes the decrypted credentials, in
the authorized-user format the existing YouTubeAuth/uploader already read,
to a 0600 file - so the proven upload path runs unchanged. Nothing here ever
logs or prints token material.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

YOUTUBE_TOKEN_NAME = "youtube"
_HKDF_INFO = b"robin-content-engine/oauth-token/v1"
_HKDF_SALT = b"robin-content-engine"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class TokenStoreError(RuntimeError):
    """Operator-safe messages only - never includes key or token material."""


@dataclass(frozen=True)
class StoredCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    scopes: tuple[str, ...]
    channel_id: str

    def authorized_user_info(self) -> dict[str, Any]:
        """The google-auth authorized-user JSON the existing YouTubeAuth reads."""
        return {
            "type": "authorized_user",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "token_uri": GOOGLE_TOKEN_URI,
            "scopes": list(self.scopes),
        }


def fernet_from_service_account(service_account_info: dict[str, Any]) -> Fernet:
    """Deterministic Fernet key derived from the service account's private key."""
    private_key = service_account_info.get("private_key")
    if not isinstance(private_key, str) or not private_key.strip():
        raise TokenStoreError("The service-account key has no private_key to derive from.")
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO
    ).derive(private_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_credentials(fernet: Fernet, credentials: StoredCredentials) -> str:
    payload = json.dumps(
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
            "scopes": list(credentials.scopes),
            "channel_id": credentials.channel_id,
        }
    ).encode("utf-8")
    return fernet.encrypt(payload).decode("ascii")


def decrypt_credentials(fernet: Fernet, ciphertext: str) -> StoredCredentials:
    try:
        raw = json.loads(fernet.decrypt(ciphertext.encode("ascii")))
    except InvalidToken as exc:
        raise TokenStoreError(
            "The stored YouTube token cannot be decrypted (was the service-account key "
            "rotated?). Run the one-time YouTube sign-in again."
        ) from exc
    except ValueError as exc:
        raise TokenStoreError("The stored YouTube token is malformed.") from exc
    try:
        return StoredCredentials(
            client_id=str(raw["client_id"]),
            client_secret=str(raw["client_secret"]),
            refresh_token=str(raw["refresh_token"]),
            scopes=tuple(str(s) for s in raw["scopes"]),
            channel_id=str(raw["channel_id"]),
        )
    except (KeyError, TypeError) as exc:
        raise TokenStoreError("The stored YouTube token is missing fields.") from exc


def save_token(database_url: str, name: str, ciphertext: str) -> None:
    """Insert or replace one encrypted token row."""
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO oauth_tokens (name, ciphertext)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE
               SET ciphertext = EXCLUDED.ciphertext, updated_at = NOW()
            """,
            (name, ciphertext),
        )


def load_token(database_url: str, name: str) -> str | None:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT ciphertext FROM oauth_tokens WHERE name = %s", (name,)
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def materialize_token_file(
    database_url: str,
    service_account_info: dict[str, Any],
    destination: Path,
    *,
    expected_channel_id: str | None = None,
) -> StoredCredentials:
    """Decrypt the stored YouTube token and write it as a 0600 authorized-user
    token.json for the existing uploader. Refuses a token issued for a
    different channel than `expected_channel_id`."""
    ciphertext = load_token(database_url, YOUTUBE_TOKEN_NAME)
    if ciphertext is None:
        raise TokenStoreError(
            "No YouTube token is stored yet. Run the one-time YouTube sign-in first."
        )
    credentials = decrypt_credentials(fernet_from_service_account(service_account_info), ciphertext)
    if expected_channel_id and credentials.channel_id != expected_channel_id:
        raise TokenStoreError(
            "The stored YouTube token belongs to a different channel than "
            "YOUTUBE_EXPECTED_CHANNEL_ID; refusing to use it."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(credentials.authorized_user_info(), handle)
    return credentials
