from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .database import JobRepository

ALLOWED_CAPTURE_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv"})
DEFAULT_STABILITY_WAIT_SECONDS = 2.0


class CaptureScanError(RuntimeError):
    """Safe operator-facing failure during local capture discovery."""


@dataclass(frozen=True)
class CaptureScanResult:
    directory: Path
    videos_discovered: int
    new_registered: int
    already_known: int
    skipped_unstable: int
    skipped_unsupported: int


def _is_stable(path: Path, wait_seconds: float) -> bool:
    """Two stat() snapshots taken `wait_seconds` apart; unchanged size/mtime
    means the file is not currently being written (e.g. by Xbox Game Bar)."""
    try:
        before = path.stat()
    except OSError:
        return False
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    try:
        after = path.stat()
    except OSError:
        return False
    return before.st_size == after.st_size and before.st_mtime == after.st_mtime


def _known_source_paths(repository: JobRepository) -> set[str]:
    known: set[str] = set()
    for job in repository.list_jobs():
        source_path = job.get("source_path")
        if source_path:
            known.add(str(Path(source_path).expanduser().resolve()))
    return known


def scan_captures(
    directory: Path,
    repository: JobRepository,
    *,
    stability_wait_seconds: float = DEFAULT_STABILITY_WAIT_SECONDS,
) -> CaptureScanResult:
    """Discover local gameplay recordings and register new ones as pending
    queue candidates. Never renders, uploads, moves, renames, or deletes the
    original files. Idempotent: re-running does not duplicate known captures.
    """
    resolved_dir = directory.expanduser().resolve()
    if not resolved_dir.is_dir():
        raise CaptureScanError(f"Capture directory does not exist: {resolved_dir}")

    known_paths = _known_source_paths(repository)

    videos_discovered = 0
    new_registered = 0
    already_known = 0
    skipped_unstable = 0
    skipped_unsupported = 0

    for entry in sorted(resolved_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in ALLOWED_CAPTURE_EXTENSIONS:
            skipped_unsupported += 1
            continue

        videos_discovered += 1
        resolved_entry = str(entry.resolve())

        if resolved_entry in known_paths:
            already_known += 1
            continue

        if not _is_stable(entry, stability_wait_seconds):
            skipped_unstable += 1
            continue

        rights_note = (
            f"Discovered via capture-scan from configured local capture "
            f"directory: {resolved_dir}. Assumed user-owned gameplay recording."
        )
        repository.enqueue_local(entry, entry.stem, rights_note)
        known_paths.add(resolved_entry)
        new_registered += 1

    return CaptureScanResult(
        directory=resolved_dir,
        videos_discovered=videos_discovered,
        new_registered=new_registered,
        already_known=already_known,
        skipped_unstable=skipped_unstable,
        skipped_unsupported=skipped_unsupported,
    )
