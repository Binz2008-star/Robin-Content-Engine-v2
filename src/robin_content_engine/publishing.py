from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .models import UploadResult
from .quality_gate import QualityGateConfig, QualityGateResult, run_quality_gate
from .uploader import YouTubeUploader
from .youtube_auth import YouTubeAuth, YouTubeAuthError

_UPLOAD_STATE_FORMAT_VERSION = "1"
_ATTEMPT_FILENAME = "upload_attempt.json"
_RECEIPT_FILENAME = "upload_receipt.json"
_MANIFEST_FILENAME = "manifest.json"

_MAX_TITLE_LENGTH = 100
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_TAG_LENGTH = 100
# YouTube's real combined-tags-string limit (all tags joined, roughly).
_MAX_TAGS_COMBINED_LENGTH = 500

_REQUIRED_MANIFEST_KEYS = ("sha256", "byte_size", "quality_gate_passed", "packaged_artifact_path")


class PublishingError(Exception):
    """Raised for any package/metadata validation failure or a safety-gate
    refusal (channel mismatch, duplicate-upload guard, ...). Also wraps a
    real uploader exception raised after upload execution has begun - see
    execute_private_upload()."""


@dataclass(frozen=True)
class PublishMetadata:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)


def build_publish_metadata(title: str, description: str, tags: Sequence[str]) -> PublishMetadata:
    """Validate manual, operator-supplied metadata against YouTube-compatible
    sensible limits. No LLM/automated generation happens here - values come
    from the operator, only whitespace-normalized."""
    clean_title = " ".join(title.split()).strip()
    if not clean_title:
        raise PublishingError("title must not be empty.")
    if len(clean_title) > _MAX_TITLE_LENGTH:
        raise PublishingError(
            f"title must be at most {_MAX_TITLE_LENGTH} characters (got {len(clean_title)})."
        )

    clean_description = description.strip()
    if not clean_description:
        raise PublishingError("description must not be empty.")
    if len(clean_description) > _MAX_DESCRIPTION_LENGTH:
        raise PublishingError(
            f"description must be at most {_MAX_DESCRIPTION_LENGTH} characters "
            f"(got {len(clean_description)})."
        )

    clean_tags: list[str] = []
    seen: set[str] = set()
    combined_length = 0
    for raw_tag in tags:
        tag = " ".join(raw_tag.split()).strip().lstrip("#")
        if not tag:
            continue
        if len(tag) > _MAX_TAG_LENGTH:
            raise PublishingError(
                f"tag {tag!r} exceeds the maximum tag length of {_MAX_TAG_LENGTH} characters."
            )
        key = tag.casefold()
        if key in seen:
            continue
        combined_length += len(tag) + (1 if clean_tags else 0)
        if combined_length > _MAX_TAGS_COMBINED_LENGTH:
            raise PublishingError(
                f"combined tag length exceeds YouTube's {_MAX_TAGS_COMBINED_LENGTH}-character "
                f"limit once {tag!r} is included."
            )
        clean_tags.append(tag)
        seen.add(key)

    return PublishMetadata(title=clean_title, description=clean_description, tags=clean_tags)


@dataclass(frozen=True)
class PackageValidation:
    package_dir: Path
    manifest_path: Path
    packaged_video_path: Path
    manifest: dict[str, Any]
    quality_gate: QualityGateResult


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_PATH_SEPARATOR_PATTERN = re.compile(r"[\\/]+")


def _split_path_components(raw: str) -> list[str]:
    """Splits raw on BOTH '\\' and '/' regardless of the host OS's own
    path-separator convention. pathlib.Path's own parsing is host-OS-
    dependent - PureWindowsPath treats both '/' and '\\' as separators,
    but PurePosixPath treats '\\' as a literal character, not a
    separator - so a manifest claiming a Windows-style
    ('..\\..\\evil.mp4') traversal would be silently swallowed into a
    single opaque component on Linux (e.g. Linux CI) while being
    correctly split into ['..', '..', 'evil.mp4'] on Windows. Splitting
    manually here makes traversal detection identical on every host OS."""
    return [part for part in _PATH_SEPARATOR_PATTERN.split(raw) if part != ""]


def _resolve_packaged_video_path(package_dir: Path, manifest: dict[str, Any]) -> Path:
    """Never trusts manifest paths blindly. quality_gate.package_short()
    stores packaged_artifact_path as str(package_dir / video_name) -
    absolute or relative, Windows- or POSIX-separated depending on the
    dest_root and host OS it was called with (all legitimate; the CLI's
    default dest_root is relative, but package_short() is also called
    directly with an absolute dest_root e.g. in tests), but it NEVER
    contains a parent-traversal ('..') or current-directory ('.') path
    component under EITHER separator syntax, since it's built purely
    from real directory/file names. Any such component is therefore
    EXPLICITLY rejected outright as tampering, before any file lookup is
    attempted - not merely silently reduced away, and identically
    whether this runs on Windows or Linux (see _split_path_components).
    Only after that explicit rejection is the FILENAME (last component)
    taken, joined under package_dir, and its resolved location double-
    checked to still be inside package_dir as defense in depth - nothing
    outside package_dir can ever be selected."""
    raw = manifest.get("packaged_artifact_path")
    if not isinstance(raw, str) or not raw.strip():
        raise PublishingError("manifest.json packaged_artifact_path is missing or empty.")

    components = _split_path_components(raw)
    if any(part in (".", "..") for part in components):
        raise PublishingError(
            "manifest.json packaged_artifact_path contains a parent-traversal or "
            "current-directory component, which is never valid for a legitimate Phase 8D "
            f"package (rejected as tampering): {raw!r}"
        )

    name = components[-1] if components else ""
    if not name:
        raise PublishingError(f"manifest.json packaged_artifact_path is invalid: {raw!r}")

    package_dir_resolved = package_dir.resolve()
    candidate = (package_dir / name).resolve()
    if not candidate.is_relative_to(package_dir_resolved):
        raise PublishingError(
            f"Packaged artifact path escapes the package directory: {raw!r} -> {candidate}"
        )
    return candidate


def validate_package(
    package_dir: Path, *, quality_gate_config: QualityGateConfig | None = None
) -> PackageValidation:
    """Validate one Phase 8D work/ready/<package>/ directory end-to-end
    before it can become upload-eligible: the manifest is well-formed and
    claims quality_gate_passed=true, the packaged MP4 exists inside the
    package directory (path-traversal-safe - see
    _resolve_packaged_video_path), its byte size and SHA-256 match what the
    manifest recorded, and the Phase 8D quality gate is re-run fresh
    against it right now rather than merely trusted from the manifest.
    Raises PublishingError with an explicit reason on the first failure.
    Never modifies or deletes anything."""
    if not package_dir.is_dir():
        raise PublishingError(f"Package directory does not exist: {package_dir}")

    manifest_path = package_dir / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PublishingError(f"manifest.json not found in package directory: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishingError(f"manifest.json is not valid JSON: {manifest_path} ({exc})") from exc
    if not isinstance(manifest, dict):
        raise PublishingError(f"manifest.json does not contain a JSON object: {manifest_path}")

    missing = [key for key in _REQUIRED_MANIFEST_KEYS if key not in manifest]
    if missing:
        raise PublishingError(
            f"manifest.json is missing required key(s) {missing}: {manifest_path}"
        )

    if manifest.get("quality_gate_passed") is not True:
        raise PublishingError(
            f"manifest.json records quality_gate_passed={manifest.get('quality_gate_passed')!r}, "
            "not True - refusing to publish a package that was never recorded as passing."
        )

    packaged_video_path = _resolve_packaged_video_path(package_dir, manifest)
    if not packaged_video_path.is_file():
        raise PublishingError(f"Packaged video not found: {packaged_video_path}")

    actual_size = packaged_video_path.stat().st_size
    expected_size = manifest.get("byte_size")
    if actual_size != expected_size:
        raise PublishingError(
            f"Packaged video size {actual_size} does not match manifest byte_size "
            f"{expected_size!r}: {packaged_video_path}"
        )

    actual_sha256 = _sha256_file(packaged_video_path)
    expected_sha256 = manifest.get("sha256")
    if actual_sha256 != expected_sha256:
        raise PublishingError(
            f"Packaged video SHA-256 {actual_sha256} does not match manifest sha256 "
            f"{expected_sha256!r}: {packaged_video_path}"
        )

    quality_gate = run_quality_gate(packaged_video_path, quality_gate_config)
    if not quality_gate.passed:
        reasons = "; ".join(f"{c.name}: {c.detail}" for c in quality_gate.failed_checks())
        raise PublishingError(
            f"Re-run quality gate FAILED for {packaged_video_path}, refusing to publish. {reasons}"
        )

    return PackageValidation(
        package_dir=package_dir,
        manifest_path=manifest_path,
        packaged_video_path=packaged_video_path,
        manifest=manifest,
        quality_gate=quality_gate,
    )


@dataclass(frozen=True)
class DryRunResult:
    validation: PackageValidation
    metadata: PublishMetadata


def dry_run(
    package_dir: Path,
    title: str,
    description: str,
    tags: Sequence[str],
    *,
    quality_gate_config: QualityGateConfig | None = None,
) -> DryRunResult:
    """Pure validation, zero network I/O: never constructs YouTubeAuth or
    YouTubeUploader, never loads an OAuth token, never calls YouTube."""
    validation = validate_package(package_dir, quality_gate_config=quality_gate_config)
    metadata = build_publish_metadata(title, description, tags)
    return DryRunResult(validation=validation, metadata=metadata)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _check_no_existing_upload_state(package_dir: Path) -> None:
    """A fast, early fail-fast check only - NOT the actual race-safety
    mechanism (see _create_upload_attempt_exclusive for that). Its only
    purpose is to reject an obviously-already-attempted package before
    wasting time on package re-validation and channel auth; two
    concurrent calls can both pass this check before either has created
    upload_attempt.json, which is exactly the check-then-write race
    _create_upload_attempt_exclusive() closes."""
    receipt_path = package_dir / _RECEIPT_FILENAME
    if receipt_path.is_file():
        raise PublishingError(
            f"A successful upload receipt already exists, refusing a duplicate upload: "
            f"{receipt_path}"
        )
    attempt_path = package_dir / _ATTEMPT_FILENAME
    if attempt_path.is_file():
        raise PublishingError(
            f"An upload attempt marker already exists (a prior attempt may be incomplete or "
            f"its outcome unknown) - refusing a new attempt: {attempt_path}. Operator "
            "reconciliation is required before retrying; there is no --force option."
        )


def _create_upload_attempt_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """The actual race-safety mechanism for upload_attempt.json: creates
    it via exclusive-create (Python's open(path, "x") maps to
    O_CREAT | O_EXCL identically on Windows and POSIX), so the
    existence-check and the creation are a single atomic filesystem
    operation rather than two separate steps. Even if two callers both
    pass _check_no_existing_upload_state()'s early check at the same
    moment (a genuine check-then-write race), only ONE of them can
    actually create this file - the other gets FileExistsError here,
    translated to PublishingError, and is refused before ever
    constructing or calling an uploader. Never overwrites an existing
    attempt marker."""
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except FileExistsError as exc:
        raise PublishingError(
            f"An upload attempt marker already exists (a prior attempt may be incomplete or "
            f"its outcome unknown) - refusing a new attempt: {path}. Operator reconciliation "
            "is required before retrying; there is no --force option."
        ) from exc


def execute_private_upload(
    package_dir: Path,
    title: str,
    description: str,
    tags: Sequence[str],
    settings: Settings,
    auth: YouTubeAuth,
    uploader_factory: Callable[..., YouTubeUploader],
    *,
    quality_gate_config: QualityGateConfig | None = None,
    now: datetime | None = None,
) -> UploadResult:
    """The only path in this module that may perform a real network call
    (via whatever uploader_factory(...) returns) - callers control exactly
    what `auth`/`uploader_factory` are, so tests can inject fakes and
    assert zero real requests are made.

    THIS FUNCTION, not its caller, owns the private-only invariant:
    uploader_factory is invoked BY this function with the exact
    construction arguments a YouTubeUploader needs, and privacy_status is
    always passed as the literal "private" from right here - never read
    from settings.youtube_privacy_status, never left for the caller to
    decide. A caller can inject a different uploader_factory for tests,
    but cannot make this function request any privacy value other than
    "private", since the value is a literal in this function's own source,
    not a parameter. This closes the gap where a factory could otherwise
    have silently constructed an uploader with a different privacy_status
    and this service would only detect it after the remote upload.

    Order of operations, each gating the next:
    1. Revalidate the package (identical checks to dry_run()).
    2. Validate metadata.
    3. Refuse if upload_attempt.json or upload_receipt.json already exists
       in package_dir - no --force option in this phase.
    4. Require settings.youtube_expected_channel_id to be configured.
    5. Load existing credentials non-interactively and verify the
       currently authenticated channel via auth.verify_current_channel()
       - never opens a browser.
    6. Require the authenticated channel ID to exactly match the
       configured expected channel ID; abort before constructing
       YouTubeUploader on any mismatch.
    7. Exclusively CREATE upload_attempt.json (no secrets/tokens) via
       _create_upload_attempt_exclusive() - not a plain write, so a
       check-then-write race against a concurrent call cannot silently
       overwrite an existing attempt.
    8. Call uploader_factory(client_secret_file=..., token_file=...,
       privacy_status="private", category_id=...) - this function's own
       hard-coded "private", regardless of settings.youtube_privacy_status
       - and upload exactly the validated packaged MP4.
    9. If anything raises from step 8 through the upload call itself, the
       attempt marker is intentionally left in place (ambiguous state -
       the remote upload may have already succeeded even though this
       response was lost) and a PublishingError wrapping the original is
       raised. No automatic cleanup, no retry.
    10. On success, confirm privacy_status == "private", then attempt to
        write an atomic upload_receipt.json. If THAT write itself fails,
        the remote upload has already succeeded but this package has no
        durable record of it - the attempt marker is preserved (not
        removed) and a PublishingError demanding operator reconciliation
        is raised, distinct from a pre-upload failure. Only once the
        receipt is durably written is the attempt marker removed.
    """
    validation = validate_package(package_dir, quality_gate_config=quality_gate_config)
    metadata = build_publish_metadata(title, description, tags)

    _check_no_existing_upload_state(package_dir)

    expected_channel_id = settings.youtube_expected_channel_id
    if not expected_channel_id:
        raise PublishingError(
            "youtube_expected_channel_id is not configured; refusing to upload without a "
            "known expected channel identity to verify against."
        )

    try:
        identity = auth.verify_current_channel()
    except YouTubeAuthError as exc:
        raise PublishingError(
            "YouTube is not authenticated for a private upload. Run 'robin-engine "
            f"youtube-auth' separately, then retry. ({exc})"
        ) from exc

    if identity.channel_id != expected_channel_id:
        raise PublishingError(
            f"Authenticated YouTube channel {identity.channel_id!r} does not match the "
            f"configured expected channel {expected_channel_id!r} - aborting before "
            "constructing an uploader or attempting any upload."
        )

    attempt_path = package_dir / _ATTEMPT_FILENAME
    started_at = (now or datetime.now(UTC)).isoformat()
    _create_upload_attempt_exclusive(
        attempt_path,
        {
            "format_version": _UPLOAD_STATE_FORMAT_VERSION,
            "package_sha256": validation.manifest["sha256"],
            "expected_channel_id": expected_channel_id,
            "authenticated_channel_id": identity.channel_id,
            "started_at": started_at,
            "intended_privacy": "private",
            "status": "started",
        },
    )

    try:
        uploader = uploader_factory(
            client_secret_file=settings.youtube_client_secret_file,
            token_file=settings.youtube_token_file,
            privacy_status="private",
            category_id=settings.youtube_category_id,
        )
        result = uploader.upload(validation.packaged_video_path, metadata)
    except Exception as exc:
        raise PublishingError(
            "Upload failed, or its outcome is unknown, after upload execution had already "
            f"begun. The attempt marker at {attempt_path} was intentionally preserved - the "
            "remote upload may have already succeeded even though this response was lost. "
            f"Do not retry automatically; operator reconciliation is required. Original "
            f"error: {exc}"
        ) from exc

    if result.privacy_status != "private":
        raise PublishingError(
            f"Uploader returned privacy_status={result.privacy_status!r}, expected 'private'. "
            f"Attempt marker preserved at {attempt_path} for operator review."
        )

    receipt_path = package_dir / _RECEIPT_FILENAME
    try:
        _write_json_atomic(
            receipt_path,
            {
                "format_version": _UPLOAD_STATE_FORMAT_VERSION,
                "package_sha256": validation.manifest["sha256"],
                "youtube_video_id": result.youtube_id,
                "channel_id": identity.channel_id,
                "privacy_status": "private",
                "uploaded_at": (now or datetime.now(UTC)).isoformat(),
            },
        )
    except Exception as exc:
        raise PublishingError(
            f"The upload to YouTube SUCCEEDED (video ID {result.youtube_id!r}), but writing "
            f"upload_receipt.json failed - the remote video now exists but this package has "
            "no durable record of it. The attempt marker at "
            f"{attempt_path} was intentionally preserved. Do not retry automatically; "
            "operator reconciliation is required (verify the video on YouTube, then manually "
            f"record or clean up as appropriate). Original error: {exc}"
        ) from exc

    attempt_path.unlink(missing_ok=True)

    return result
