import asyncio
import logging
from pathlib import Path
from typing import Annotated

import structlog
import typer

from . import __version__
from .config import Settings
from .database import JobRepository
from .pipeline import ContentEngine
from .youtube_auth import AuthState, YouTubeAuth, YouTubeAuthError

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


@app.command()
def version() -> None:
    """Print the installed engine version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
