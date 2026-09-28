"""Google Drive footage source - read the channel's OWN videos from a
Google Takeout export in Drive.

YouTube refuses yt-dlp downloads from cloud runners ("Sign in to confirm
you're not a bot"; probe run 36367070647, 0/10), so a PC-less production
runner cannot pull footage from the channel itself. Instead the owner
exports their own YouTube videos once with Google Takeout ("Add to Drive")
and shares that folder with a read-only service account. This module:

- lists the Takeout archives in that Drive folder,
- downloads one archive at a time (chunked, resumable per chunk),
- extracts ONLY the video files from it (zip-slip safe, streaming),
- matches each extracted file back to its channel video.

Read-only by design: the Drive scope is drive.readonly, nothing is written
to Drive, the database or YouTube. Matching never guesses - an ambiguous
file (duplicate titles with no duration evidence) is left unmatched, just
like the conservative game detector leaves ambiguous titles unclassified.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".3gp"})
ARCHIVE_EXTENSIONS = (".zip",)

# Takeout names duplicate titles "<title>(1).mp4", "<title>(2).mp4", ...
_DUPLICATE_SUFFIX_RE = re.compile(r"\(\d+\)$")

# Default duration tolerance when disambiguating same-title videos: the
# YouTube API reports whole seconds and containers round differently.
DURATION_TOLERANCE_SECONDS = 2.0

_CHUNK_BYTES = 32 * 1024 * 1024


class DriveSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DriveArchive:
    file_id: str
    name: str
    size_bytes: int | None


@dataclass(frozen=True)
class ChannelVideoRef:
    video_id: str
    title: str
    duration_seconds: int | None


def build_drive_service(service_account_info: dict[str, Any]) -> Any:
    """Drive v3 client authenticated as a service account with the
    read-only Drive scope. The owner shares the Takeout folder with the
    service account's email (Viewer); nothing else is accessible."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
        service_account_info, scopes=[DRIVE_READONLY_SCOPE]
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def list_archives(service: Any, folder_id: str) -> list[DriveArchive]:
    """All Takeout archives directly inside `folder_id`, oldest first
    (Takeout numbers parts in creation order). Follows pagination."""
    if not folder_id or "'" in folder_id:
        raise DriveSourceError("A valid Drive folder id is required.")
    archives: list[DriveArchive] = []
    page_token: str | None = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, size)",
                orderBy="createdTime",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in response.get("files", []):
            name = str(item.get("name", ""))
            if name.lower().endswith(ARCHIVE_EXTENSIONS):
                size = item.get("size")
                archives.append(
                    DriveArchive(
                        file_id=str(item["id"]),
                        name=name,
                        size_bytes=int(size) if size is not None else None,
                    )
                )
        page_token = response.get("nextPageToken")
        if not page_token:
            return archives


def download_archive(service: Any, archive: DriveArchive, dest_dir: Path) -> Path:
    """Download one archive to `dest_dir` in chunks. Re-uses a complete
    earlier download (same size) instead of fetching it again."""
    from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / _safe_filename(archive.name)
    if (
        target.is_file()
        and archive.size_bytes is not None
        and target.stat().st_size == archive.size_bytes
    ):
        return target

    partial = target.with_suffix(target.suffix + ".part")
    request = service.files().get_media(fileId=archive.file_id, supportsAllDrives=True)
    try:
        with partial.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request, chunksize=_CHUNK_BYTES)
            done = False
            while not done:
                _status, done = downloader.next_chunk(num_retries=3)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise DriveSourceError(f"download of {archive.name} failed: {exc}") from exc
    partial.replace(target)
    return target


def extract_videos(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Extract only video files from a Takeout zip into `dest_dir` (flat).
    Entries that would escape `dest_dir` (absolute paths, '..') are refused.
    Existing complete files are kept, so re-running is cheap."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise DriveSourceError(f"unsafe archive entry refused: {info.filename!r}")
                if member.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                target = dest_dir / _safe_filename(member.name)
                if not target.is_file() or target.stat().st_size != info.file_size:
                    with archive.open(info) as source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink, length=_CHUNK_BYTES)
                extracted.append(target)
    except zipfile.BadZipFile as exc:
        raise DriveSourceError(f"{archive_path.name} is not a valid zip archive: {exc}") from exc
    return extracted


def normalize_title(value: str) -> str:
    """Comparable form of a video title / Takeout file stem: drops the file
    extension and Takeout's "(n)" duplicate suffix, then keeps only letters
    and digits (any script, so Arabic titles compare correctly), casefolded.
    Takeout replaces characters that are illegal in file names, so
    punctuation and emoji cannot be compared reliably and are ignored."""
    stem = value
    suffix = PurePosixPath(value).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        stem = value[: -len(suffix)]
    stem = _DUPLICATE_SUFFIX_RE.sub("", stem.strip())
    stem = unicodedata.normalize("NFKC", stem).casefold()
    return "".join(ch for ch in stem if unicodedata.category(ch)[0] in ("L", "N"))


def match_channel_video(
    file_name: str,
    duration_seconds: float | None,
    candidates: Sequence[ChannelVideoRef],
    *,
    tolerance_seconds: float = DURATION_TOLERANCE_SECONDS,
) -> ChannelVideoRef | None:
    """The channel video an extracted Takeout file belongs to, or None.

    Titles must match after normalization. When several channel videos share
    the title (the channel has e.g. many "Archived Gaming Clip" uploads), the
    file's duration must single out exactly one of them; without a duration,
    or when none / several remain, the file is left unmatched rather than
    guessed."""
    key = normalize_title(file_name)
    if not key:
        return None
    same_title = [c for c in candidates if normalize_title(c.title) == key]
    if not same_title:
        return None
    if len(same_title) == 1 and (
        duration_seconds is None or same_title[0].duration_seconds is None
    ):
        # A unique title with no duration evidence either way is a match;
        # a unique title whose duration CONTRADICTS the file falls through
        # to the tolerance check below and is refused.
        return same_title[0]
    if duration_seconds is None:
        return None
    close = [
        c
        for c in same_title
        if c.duration_seconds is not None
        and abs(c.duration_seconds - duration_seconds) <= tolerance_seconds
    ]
    return close[0] if len(close) == 1 else None


def match_all(
    files: Iterable[tuple[Path, float | None]],
    candidates: Sequence[ChannelVideoRef],
) -> tuple[dict[Path, ChannelVideoRef], list[Path]]:
    """Match many extracted files at once. A channel video may be claimed by
    at most one file; if two files resolve to the same video, both are
    treated as unmatched (never guessed). Returns (matched, unmatched)."""
    tentative: dict[Path, ChannelVideoRef] = {}
    unmatched: list[Path] = []
    for path, duration in files:
        ref = match_channel_video(path.name, duration, candidates)
        if ref is None:
            unmatched.append(path)
        else:
            tentative[path] = ref

    claims: dict[str, list[Path]] = {}
    for path, ref in tentative.items():
        claims.setdefault(ref.video_id, []).append(path)
    matched: dict[Path, ChannelVideoRef] = {}
    for path, ref in tentative.items():
        if len(claims[ref.video_id]) == 1:
            matched[path] = ref
        else:
            unmatched.append(path)
    return matched, unmatched


def _safe_filename(name: str) -> str:
    """A single path component safe to create on disk."""
    cleaned = name.replace("/", "_").replace("\\", "_").strip() or "unnamed"
    return cleaned if cleaned not in (".", "..") else "unnamed"
