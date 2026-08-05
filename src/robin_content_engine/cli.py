import asyncio
import logging

import structlog
import typer

from . import __version__
from .config import Settings
from .pipeline import ContentEngine

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


@app.command("run-once")
def run_once(
    render_only: bool = typer.Option(
        False,
        "--render-only",
        help="Render and mark the job rendered without uploading to YouTube.",
    ),
) -> None:
    """Claim and process one pending job."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    job_id = asyncio.run(ContentEngine(settings).run_once(upload=not render_only))
    if job_id is None:
        typer.echo("No pending jobs.")
    else:
        typer.echo(f"Processed job {job_id}.")


@app.command()
def version() -> None:
    """Print the installed engine version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
