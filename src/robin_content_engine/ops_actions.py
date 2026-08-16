"""Shared production operations used by BOTH the studio API (api.py) and
the lightweight ops dashboard (controlpanel.py), so there is a single
implementation of every operator action instead of two copies.

Every function returns a JSON-serializable dict; `ok` is False and `output`
carries an operator-safe message when the action raised.
"""

from __future__ import annotations

import contextlib
from typing import Any

from .ai_logic import ContentGenerator
from .capture_scan import scan_captures
from .channel_import import import_video_as_short, list_long_videos
from .channel_metadata import ChannelMetadataError, ChannelMetadataFixer
from .config import Settings
from .database import JobRepository
from .production_runner import build_production_metadata, production_status, run_production_once
from .publishing import dry_run, execute_private_upload
from .uploader import YouTubeUploader
from .youtube_auth import AuthState, YouTubeAuth


def _repo(settings: Settings) -> JobRepository:
    return JobRepository(settings.database_url, settings.max_job_attempts)


def _auth(settings: Settings) -> YouTubeAuth:
    return YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)


def _generator(settings: Settings) -> ContentGenerator:
    return ContentGenerator(
        settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model
    )


def _wrap(fn: Any) -> dict[str, Any]:
    try:
        return {"ok": True, "output": fn()}
    except Exception as exc:
        return {"ok": False, "output": f"{type(exc).__name__}: {exc}"}


def system_info(settings: Settings) -> dict[str, Any]:
    token_ok = False
    with contextlib.suppress(Exception):
        token_ok = _auth(settings).state() == AuthState.AUTHENTICATED
    db_ok = False
    with contextlib.suppress(Exception), _repo(settings).running() as repo:
        db_ok = bool(repo.ping())
    return {
        "youtube_authenticated": token_ok,
        "database": "connected" if db_ok else "unavailable",
        "metadata_language": getattr(settings, "youtube_metadata_language", "arabic"),
        "highlight_min_seconds": settings.highlight_min_seconds,
        "highlight_max_seconds": settings.highlight_max_seconds,
    }


def status(settings: Settings) -> dict[str, Any]:
    with _repo(settings).running() as repo:
        report = production_status(repo, settings)
    return {
        "counts": {
            "awaiting_rights": report.awaiting_rights,
            "rejected": report.rejected,
            "rights_approved_eligible": report.rights_approved_eligible,
            "processing": report.processing,
            "packaged": report.packaged,
            "uploaded_private": report.uploaded_private,
            "ambiguous": report.ambiguous,
            "inactive": report.inactive,
        },
        "jobs": [
            {"job_id": job.job_id, "source_title": job.source_title, "state": job.state}
            for job in report.jobs
        ],
    }


def scan(settings: Settings) -> dict[str, Any]:
    def run() -> str:
        with _repo(settings).running() as repo:
            result = scan_captures(settings.capture_source_dir, repo)
        return (
            f"Videos discovered: {result.videos_discovered}\n"
            f"New captures registered: {result.new_registered}\n"
            f"Already known: {result.already_known}\n"
            f"Skipped unstable: {result.skipped_unstable}"
        )

    return _wrap(run)


def sync(settings: Settings) -> dict[str, Any]:
    def run() -> str:
        from .channel_repository import ChannelRepository
        from .youtube_sync import YouTubeChannelSync

        sync = YouTubeChannelSync(_auth(settings), settings.youtube_expected_channel_id)
        snapshot = sync.fetch_snapshot()
        with ChannelRepository(settings.database_url).running() as repo:
            stored = repo.save_snapshot(snapshot)
        return f"Snapshot refreshed: {stored} videos stored."

    return _wrap(run)


def approve(settings: Settings, job_id: int, note: str | None = None) -> dict[str, Any]:
    note = (note or "Approved from the control panel by the operator.").strip()

    def run() -> str:
        with _repo(settings).running() as repo:
            approved = repo.approve_rights(job_id, note)
        if approved is None:
            return "job is not reviewable"
        return f"Rights approved for job {job_id} (status={approved['status']})."

    return _wrap(run)


def _run_once_inner(settings: Settings, upload: bool) -> str:
    once = run_production_once(_repo(settings), settings)
    lines = [f"Capture scan: {once.capture_scan.new_registered} new registered."]
    for skipped in once.skipped:
        lines.append(f"Skipped job {skipped.job_id}: {skipped.reason}")
    if once.terminal_failure is not None:
        lines.append(
            f"Job {once.terminal_failure.job_id} failed permanently: "
            f"{once.terminal_failure.reason}"
        )
        return "\n".join(lines)
    if once.selected_job_id is None:
        lines.append("NO ELIGIBLE JOB")
        return "\n".join(lines)
    result = once.run
    assert result is not None
    lines.append(
        f"Job {result.job_id}: {result.source_title} | rank {result.rank} | "
        f"window {result.start_seconds:.0f}s-{result.end_seconds:.0f}s | "
        f"quality gate {'PASS' if result.quality_gate.passed else 'FAIL'}"
    )
    if not result.quality_gate.passed:
        return "\n".join(lines)
    assert result.package is not None
    lines.append(f"Package: {result.package.package_dir}")
    title, description, tags = build_production_metadata(result.source_title, settings)
    lines.append(f"Title: {title}")
    if not upload:
        dry_run(result.package.package_dir, title, description, tags)
        lines.append("PUBLISH DRY RUN PASS (no upload)")
        return "\n".join(lines)
    upload_result = execute_private_upload(
        result.package.package_dir,
        title,
        description,
        tags,
        settings,
        _auth(settings),
        YouTubeUploader,
    )
    lines.append(f"UPLOAD SUCCESS — video ID {upload_result.youtube_id}")
    return "\n".join(lines)


def run_once(settings: Settings, upload: bool = True) -> dict[str, Any]:
    return _wrap(lambda: _run_once_inner(settings, upload))


def make_public(settings: Settings) -> dict[str, Any]:
    def run() -> str:
        import psycopg
        from googleapiclient.discovery import build  # type: ignore[import-untyped]

        auth = _auth(settings)
        credentials = auth.load_credentials()
        identity = auth.fetch_channel_identity(credentials)
        if (
            settings.youtube_expected_channel_id
            and identity.channel_id != settings.youtube_expected_channel_id
        ):
            raise RuntimeError("channel mismatch")
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        with psycopg.connect(settings.database_url) as conn:
            rows = conn.execute(
                "SELECT video_id FROM youtube_videos "
                "WHERE is_current = TRUE AND privacy_status = 'private'"
            ).fetchall()
        made = 0
        for (video_id,) in rows:
            youtube.videos().update(
                part="status",
                body={"id": video_id, "status": {"privacyStatus": "public"}},
            ).execute()
            made += 1
        return f"Made {made} private video(s) public."

    return _wrap(run)


def metadata_fix(settings: Settings, apply: bool = False, max_updates: int = 20) -> dict[str, Any]:
    def run() -> str:
        fixer = ChannelMetadataFixer(settings, _auth(settings), _generator(settings))
        discovered = fixer.discover()
        lines = [f"Videos needing metadata fixes: {len(discovered)}"]
        generated = 0
        for entry in fixer.plan.pending():
            if entry.new_title is not None:
                continue
            try:
                fixer.generate_for(entry)
                generated += 1
            except ChannelMetadataError as exc:
                lines.append(f"  generation failed {entry.video_id}: {exc}")
        lines.append(f"Generated: {generated}")
        if apply:
            applied, failed, failures = fixer.apply(max_updates=max_updates)
            lines.append(f"Applied: {applied}, failed: {failed}")
            for vid, err in failures:
                lines.append(f"  {vid}: {err}")
        else:
            lines.append("Plan built (not applied). Use apply to write to YouTube.")
        return "\n".join(lines)

    return _wrap(run)


def metadata_plan_status(settings: Settings) -> dict[str, Any]:
    """Read-only summary of the resumable metadata-fix plan, including any
    operator-queued corrections (e.g. mislabeled videos fixed by hand)."""
    fixer = ChannelMetadataFixer(settings, _auth(settings), _generator(settings))
    return {
        "plan_file": str(fixer.plan.path),
        "pending": [
            {
                "video_id": entry.video_id,
                "old_title": entry.old_title,
                "new_title": entry.new_title,
                "detail": entry.detail,
            }
            for entry in fixer.plan.pending()
        ],
        "done_count": fixer.plan.done_count(),
    }


def import_video(settings: Settings, video_id: str, upload: bool = False) -> dict[str, Any]:
    def run() -> str:
        repo = _repo(settings)
        job_id, result = import_video_as_short(video_id, repo, settings, rank=1)
        lines = [
            f"Imported {video_id} as job {job_id}.",
            f"Window: {result.start_seconds:.0f}s-{result.end_seconds:.0f}s | "
            f"quality gate {'PASS' if result.quality_gate.passed else 'FAIL'}",
        ]
        if upload and result.quality_gate.passed and result.package is not None:
            title, description, tags = build_production_metadata(result.source_title, settings)
            upload_result = execute_private_upload(
                result.package.package_dir,
                title,
                description,
                tags,
                settings,
                _auth(settings),
                YouTubeUploader,
            )
            lines.append(f"UPLOAD SUCCESS — video ID {upload_result.youtube_id}")
        else:
            lines.append("Not uploaded (queued for the next scheduled run).")
        return "\n".join(lines)

    return _wrap(run)


def long_videos(settings: Settings, limit: int = 30, min_seconds: int = 60) -> dict[str, Any]:
    return {"ok": True, "videos": list_long_videos(settings, min_seconds=min_seconds, limit=limit)}
