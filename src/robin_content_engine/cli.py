import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any

import structlog
import typer

from . import __version__
from .capture_scan import CaptureScanError, scan_captures
from .channel_repository import ChannelRepository
from .config import Settings
from .database import JobRepository
from .pipeline import ContentEngine
from .youtube_auth import AuthState, YouTubeAuth, YouTubeAuthError
from .youtube_sync import YouTubeChannelSync, YouTubeSyncError

app = typer.Typer(no_args_is_help=True, help="Robin Content Engine")


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


@app.command("enqueue-local")
def enqueue_local(
    source: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    title: Annotated[
        str,
        typer.Option("--title", help="Internal description of the footage."),
    ],
    rights_note: Annotated[
        str,
        typer.Option(
            "--rights-note",
            help="Why you are allowed to edit and publish this footage.",
        ),
    ],
    confirm_rights: Annotated[
        bool,
        typer.Option(
            "--confirm-rights",
            help="Confirm that you own the footage or hold a publishing licence.",
        ),
    ] = False,
) -> None:
    """Add one owned or licensed local video to the queue."""
    if not confirm_rights:
        raise typer.BadParameter("Pass --confirm-rights only after verifying publishing rights.")

    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        job_id = repository.enqueue_local(source, title, rights_note)
    typer.echo(f"Queued job {job_id}.")


@app.command("run-once")
def run_once(
    render_only: Annotated[
        bool,
        typer.Option(
            "--render-only",
            help="Render and mark the job rendered without uploading to YouTube.",
        ),
    ] = False,
) -> None:
    """Claim and process one pending job."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    job_id = asyncio.run(ContentEngine(settings).run_once(upload=not render_only))
    if job_id is None:
        typer.echo("No pending jobs.")
    else:
        typer.echo(f"Processed job {job_id}.")


@app.command("youtube-auth")
def youtube_auth() -> None:
    """Run interactive YouTube OAuth and verify the authenticated channel."""
    settings = Settings()  # type: ignore[call-arg]
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    try:
        channel = auth.authenticate_and_verify()
    except YouTubeAuthError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("YouTube authentication successful.")
    typer.echo(f"Channel: {channel.title}")
    typer.echo(f"Channel ID: {channel.channel_id}")
    if channel.custom_url:
        typer.echo(f"Custom URL: {channel.custom_url}")


@app.command("youtube-status")
def youtube_status() -> None:
    """Check YouTube auth state without ever opening a browser."""
    settings = Settings()  # type: ignore[call-arg]
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    state = auth.state()
    if state != AuthState.AUTHENTICATED:
        typer.echo(f"YouTube auth state: {state.value}")
        typer.echo("Run: robin-engine youtube-auth")
        return
    try:
        channel = auth.verify_current_channel()
    except YouTubeAuthError as exc:
        typer.echo(f"YouTube auth state: {AuthState.REFRESH_FAILED.value}")
        typer.echo(str(exc))
        typer.echo("Run: robin-engine youtube-auth")
        return
    typer.echo("YouTube auth state: authenticated")
    typer.echo(f"Channel: {channel.title}")
    typer.echo(f"Channel ID: {channel.channel_id}")
    if channel.custom_url:
        typer.echo(f"Custom URL: {channel.custom_url}")


@app.command("youtube-sync")
def youtube_sync() -> None:
    """Read the authenticated channel inventory and save a Neon snapshot."""
    settings = Settings()  # type: ignore[call-arg]
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    service = YouTubeChannelSync(
        auth,
        expected_channel_id=settings.youtube_expected_channel_id,
    )
    try:
        snapshot = service.fetch_snapshot()
    except (YouTubeAuthError, YouTubeSyncError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    repository = ChannelRepository(settings.database_url)
    with repository.running():
        stored_count = repository.save_snapshot(snapshot)

    channel = snapshot.channel
    typer.echo("YouTube channel sync successful.")
    typer.echo(f"Channel: {channel.title}")
    typer.echo(f"Channel ID: {channel.channel_id}")
    typer.echo(f"Uploads discovered: {snapshot.discovered_video_count}")
    typer.echo(f"Videos stored: {stored_count}")
    if channel.view_count is not None:
        typer.echo(f"Channel views: {channel.view_count}")
    if channel.subscriber_count is not None:
        typer.echo(f"Subscribers: {channel.subscriber_count}")


@app.command("capture-scan")
def capture_scan(
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Override the configured local capture directory."),
    ] = None,
) -> None:
    """Discover local gameplay recordings and register new ones as pending
    queue candidates. Never renders, uploads, moves, renames, or deletes
    the original files."""
    settings = Settings()  # type: ignore[call-arg]
    directory = path or settings.capture_source_dir

    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    try:
        with repository.running():
            result = scan_captures(
                directory,
                repository,
                stability_wait_seconds=settings.capture_stability_wait_seconds,
            )
    except CaptureScanError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("Capture scan completed.")
    typer.echo(f"Directory: {result.directory}")
    typer.echo(f"Videos discovered: {result.videos_discovered}")
    typer.echo(f"New captures registered: {result.new_registered}")
    typer.echo(f"Already known: {result.already_known}")
    typer.echo(f"Skipped unstable: {result.skipped_unstable}")
    typer.echo(f"Skipped unsupported: {result.skipped_unsupported}")


def _print_job_rights_summary(job: dict[str, Any]) -> None:
    typer.echo(f"Job {job['id']}")
    typer.echo(f"  Title: {job['source_title']}")
    typer.echo(f"  Source path: {job.get('source_path')}")
    typer.echo(f"  Status: {job['status']}")
    typer.echo(f"  Rights confirmed: {job['rights_confirmed']}")
    typer.echo(f"  Rights note: {job.get('rights_note') or '(none)'}")


@app.command("rights-list")
def rights_list(
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show every job, not just those awaiting rights review."),
    ] = False,
) -> None:
    """List source candidates. Defaults to only those still awaiting
    explicit operator rights verification - pending/unconfirmed sources
    and sources auto-quarantined by run_once() before review. Explicitly
    operator-rejected sources are excluded from this default view."""
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        jobs = repository.list_jobs() if show_all else repository.list_pending_rights_review()

    if not jobs:
        typer.echo("No jobs in the queue." if show_all else "No jobs awaiting rights review.")
        return

    for index, job in enumerate(jobs):
        if index:
            typer.echo("")
        _print_job_rights_summary(job)


@app.command("rights-show")
def rights_show(job_id: Annotated[int, typer.Argument(help="Job ID to inspect.")]) -> None:
    """Show the rights-relevant fields for one job."""
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        job = repository.get_job(job_id)
    if job is None:
        raise typer.BadParameter(f"Job {job_id} not found.")
    _print_job_rights_summary(job)


@app.command("rights-approve")
def rights_approve(
    job_id: Annotated[int, typer.Argument(help="Job ID to approve.")],
    note: Annotated[
        str, typer.Option("--note", help="Explicit rights verification note.")
    ],
) -> None:
    """Explicitly confirm publishing rights for one reviewable source.

    Reviewable means pending with unconfirmed rights, OR auto-quarantined
    by run_once() (quarantine_unconfirmed()) while still unconfirmed -
    that auto-quarantine is a safety side effect, not an operator
    decision, so it stays approvable. Explicitly operator-rejected jobs
    and any other quarantined/terminal state are NOT reviewable here.
    This never claims, renders, generates content, or uploads anything -
    it only marks the source rights-confirmed (and, if it was auto-
    quarantined, restores status to pending) so the existing queue rules
    become eligible to pick it up later. rights_confirmed = TRUE means the
    operator approves the source's provenance to proceed through Robin's
    rights gate - it does NOT guarantee every frame/audio element is
    copyright-clear, that monetization is guaranteed, or that YouTube's
    reused-content policy is satisfied. Later quality/rights QA must
    still catch third-party-content issues before publishing.
    """
    cleaned_note = note.strip()
    if not cleaned_note:
        raise typer.BadParameter("--note must not be empty.")

    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        existing = repository.get_job(job_id)
        if existing is None:
            raise typer.BadParameter(f"Job {job_id} not found.")
        approved = repository.approve_rights(job_id, cleaned_note)

    if approved is None:
        raise typer.BadParameter(
            f"Job {job_id} is not in a reviewable state "
            f"(status={existing['status']}, rights_confirmed={existing['rights_confirmed']}). "
            "Only pending or auto-quarantined jobs with unconfirmed rights can be approved."
        )

    typer.echo(f"Rights approved for job {job_id}.")
    typer.echo(f"Status: {approved['status']}")
    typer.echo(f"Rights confirmed: {approved['rights_confirmed']}")


@app.command("rights-reject")
def rights_reject(
    job_id: Annotated[int, typer.Argument(help="Job ID to reject.")],
    note: Annotated[str, typer.Option("--note", help="Reason the source was rejected.")],
) -> None:
    """Reject one reviewable source. Reviewable means pending with
    unconfirmed rights, OR auto-quarantined by run_once() while still
    unconfirmed; an already operator-rejected job is not reviewable and
    cannot be rejected (or approved) again. Rights remain unconfirmed; the
    job is quarantined and removed from normal processing. The source
    file and database row are never deleted - the record is kept for
    audit/history.
    """
    cleaned_note = note.strip()
    if not cleaned_note:
        raise typer.BadParameter("--note must not be empty.")

    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        existing = repository.get_job(job_id)
        if existing is None:
            raise typer.BadParameter(f"Job {job_id} not found.")
        rejected = repository.reject_rights(job_id, cleaned_note)

    if rejected is None:
        raise typer.BadParameter(
            f"Job {job_id} is not in a reviewable state "
            f"(status={existing['status']}, rights_confirmed={existing['rights_confirmed']}). "
            "Only pending or auto-quarantined jobs with unconfirmed rights can be rejected."
        )

    typer.echo(f"Rights rejected for job {job_id}.")
    typer.echo(f"Status: {rejected['status']}")
    typer.echo(f"Rights confirmed: {rejected['rights_confirmed']}")


@app.command()
def version() -> None:
    """Print the installed engine version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
