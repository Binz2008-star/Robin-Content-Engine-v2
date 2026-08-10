import asyncio
import dataclasses
import json
import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

import structlog
import typer

from . import __version__
from .captioner import CaptionError, burn_captions
from .capture_scan import CaptureScanError, scan_captures
from .channel_repository import ChannelRepository
from .clip_cutter import ClipCutError, cut_clip
from .clip_selector import (
    ClipSelectionError,
    HighlightCandidate,
    WindowSelectorConfig,
    generate_candidate_windows,
    suppress_overlaps,
)
from .config import Settings
from .database import JobRepository
from .highlight_features import (
    FeatureExtractionError,
    compute_scene_density,
    extract_audio_activity,
    extract_motion_activity,
    generate_time_windows,
)
from .highlight_scoring import score_windows
from .models import HighlightCandidateResult, HighlightScanResult
from .pipeline import ContentEngine
from .publishing import PublishingError, dry_run, execute_private_upload
from .quality_gate import PackagingError, package_short, run_quality_gate
from .scene_detector import SceneBoundary, SceneDetectionError, detect_scenes
from .transcription import FasterWhisperRecognizer, TranscriptionError
from .uploader import YouTubeUploader
from .vertical_reframe import VerticalReframeError, reframe_to_vertical
from .youtube_auth import AuthState, YouTubeAuth, YouTubeAuthError
from .youtube_sync import YouTubeChannelSync, YouTubeSyncError

app = typer.Typer(no_args_is_help=True, help="Robin Content Engine")

# Fixed analysis-grid granularity for highlight-scan. Not CLI-exposed in this
# MVP to keep the command surface narrow; detector/window/scoring tunables
# remain configurable at the module level via their respective Config
# dataclasses for anyone calling these modules directly.
_HIGHLIGHT_WINDOW_SECONDS = 1.0


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


def _load_rights_confirmed_local_job(job_id: int) -> tuple[dict[str, Any], Path]:
    """Shared read-only job lookup for highlight-scan/highlight-cut: a
    single JobRepository.get_job() read, requiring confirmed rights and a
    valid local source file. Never claims the job or mutates any state."""
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    with repository.running():
        job = repository.get_job(job_id)

    if job is None:
        raise typer.BadParameter(f"Job {job_id} not found.")
    if not job["rights_confirmed"]:
        raise typer.BadParameter(
            f"Job {job_id} does not have confirmed publishing rights "
            "(rights_confirmed=False). Run rights-approve first."
        )
    source_path = job.get("source_path")
    if not source_path:
        raise typer.BadParameter(
            f"Job {job_id} has no local source_path to analyze "
            "(remote sources are not supported)."
        )
    video_path = Path(source_path)
    if not video_path.is_file():
        raise typer.BadParameter(f"Source file does not exist: {video_path}")
    return job, video_path


def _run_highlight_analysis(
    video_path: Path, top_n: int
) -> tuple[list[SceneBoundary], list[HighlightCandidate]]:
    """Shared read-only analysis pipeline used by both highlight-scan and
    highlight-cut: scene detection, deterministic audio/motion/scene
    signal scoring, and candidate ranking/dedup. Reuses the existing
    scene_detector/highlight_features/highlight_scoring/clip_selector
    functions unmodified - never claims a job, never mutates the DB,
    never renders, never uploads.

    suppress_overlaps() is deterministic given the same ranked candidate
    pool: the first min(top_n_a, top_n_b) accepted candidates are
    identical regardless of top_n, since top_n only controls when the
    greedy scan stops early. Calling this with top_n=N and indexing
    result[N-1] therefore always yields the exact same candidate that
    highlight-scan would show at rank N.
    """
    scenes = detect_scenes(video_path)
    duration_seconds = scenes[-1].end_seconds

    windows = generate_time_windows(duration_seconds, _HIGHLIGHT_WINDOW_SECONDS)
    raw_rms, raw_flux = extract_audio_activity(video_path, windows)
    raw_motion = extract_motion_activity(video_path, windows)
    raw_scene = compute_scene_density(scenes, windows)

    window_scores = score_windows(windows, raw_rms, raw_flux, raw_motion, raw_scene)

    selector_config = WindowSelectorConfig()
    ranked_candidates = generate_candidate_windows(window_scores, selector_config)
    selected = suppress_overlaps(
        ranked_candidates,
        iou_threshold=selector_config.overlap_iou_threshold,
        containment_threshold=selector_config.containment_threshold,
        top_n=top_n,
    )
    return scenes, selected


def _highlight_cut_filename(
    job_id: int, rank: int, start_seconds: float, end_seconds: float
) -> str:
    start_ms = round(start_seconds * 1000)
    end_ms = round(end_seconds * 1000)
    return f"job-{job_id}-highlight-{rank:02d}-{start_ms}-{end_ms}.mp4"


@app.command("highlight-scan")
def highlight_scan(
    job_id: Annotated[int, typer.Argument(help="Job ID to analyze.")],
    top: Annotated[
        int, typer.Option("--top", help="Number of ranked candidates to return.")
    ] = 5,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON instead of a table.")
    ] = False,
) -> None:
    """Read-only deterministic highlight analysis for one job's local source
    video: scene detection, audio/motion signal scoring, candidate window
    search, and overlap suppression. Prints ranked timestamps, scores, and
    a signal breakdown only.

    Never claims the job, never increments attempts, never writes any
    generated_*/output_path/status field, never renders, never uploads,
    never calls an LLM. The only database interaction is a single read via
    JobRepository.get_job().
    """
    job, video_path = _load_rights_confirmed_local_job(job_id)

    try:
        scenes, selected = _run_highlight_analysis(video_path, top)
        duration_seconds = scenes[-1].end_seconds
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    result = HighlightScanResult(
        job_id=job_id,
        source_title=job["source_title"],
        duration_seconds=duration_seconds,
        candidates=[
            HighlightCandidateResult(
                rank=index + 1,
                start_seconds=candidate.start_seconds,
                end_seconds=candidate.end_seconds,
                duration_seconds=candidate.duration_seconds,
                score=candidate.score,
                signals={
                    "audio": candidate.audio_score,
                    "motion": candidate.motion_score,
                    "scene": candidate.scene_signal,
                },
                reason=candidate.reason,
            )
            for index, candidate in enumerate(selected)
        ],
    )

    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        return

    typer.echo(f"Job {result.job_id}: {result.source_title}")
    typer.echo(f"Source duration: {result.duration_seconds:.1f}s")
    typer.echo(f"Scenes detected: {len(scenes)}")
    typer.echo(f"Candidates after overlap suppression: {len(result.candidates)}")
    if not result.candidates:
        typer.echo("No candidates found.")
        return
    for candidate in result.candidates:
        typer.echo(
            f"  #{candidate.rank} [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] "
            f"({candidate.duration_seconds:.1f}s) score={candidate.score:.3f} - {candidate.reason}"
        )
        typer.echo(
            f"      audio={candidate.signals['audio']:.3f} "
            f"motion={candidate.signals['motion']:.3f} "
            f"scene={candidate.signals['scene']:.3f}"
        )


@app.command("highlight-cut")
def highlight_cut(
    job_id: Annotated[int, typer.Argument(help="Job ID to cut a clip from.")],
    rank: Annotated[
        int,
        typer.Option(
            "--rank", help="Which ranked highlight-scan candidate to cut (1 = top-ranked)."
        ),
    ] = 1,
) -> None:
    """Cut one ranked highlight candidate from a job's local source video
    into a new local MP4 file. Reuses the same deterministic highlight
    analysis as highlight-scan (same configs, same ranking) so --rank N
    always matches highlight-scan's rank N exactly.

    This never claims the job, never increments attempts, never changes
    job status, never touches rights state, never calls an LLM or
    YouTube, never uploads, and never runs the render/publish pipeline.
    The only database interaction is a single read via
    JobRepository.get_job(). The original source file is never modified,
    moved, renamed, or deleted, and an existing output file is never
    overwritten.
    """
    if rank < 1:
        raise typer.BadParameter("--rank must be >= 1.")

    job, video_path = _load_rights_confirmed_local_job(job_id)

    try:
        _scenes, selected = _run_highlight_analysis(video_path, rank)
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if len(selected) < rank:
        raise typer.BadParameter(
            f"Job {job_id} only has {len(selected)} candidate(s) after overlap "
            f"suppression; --rank {rank} is out of range."
        )
    candidate = selected[rank - 1]

    settings = Settings()  # type: ignore[call-arg]
    output_dir = settings.work_dir / "highlights"
    filename = _highlight_cut_filename(
        job_id, rank, candidate.start_seconds, candidate.end_seconds
    )
    output_path = output_dir / filename

    try:
        result = cut_clip(video_path, output_path, candidate.start_seconds, candidate.end_seconds)
    except ClipCutError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Job {job_id}: {job['source_title']}")
    typer.echo(f"Rank: {rank}")
    typer.echo(f"Source path: {video_path}")
    typer.echo(f"Start: {result.start_seconds:.1f}s")
    typer.echo(f"End: {result.end_seconds:.1f}s")
    typer.echo(f"Duration: {result.duration_seconds:.1f}s")
    typer.echo(f"Score: {candidate.score:.3f}")
    typer.echo(f"Output path: {result.output_path}")


def _highlight_reframe_filename(
    job_id: int, rank: int, start_seconds: float, end_seconds: float
) -> str:
    start_ms = round(start_seconds * 1000)
    end_ms = round(end_seconds * 1000)
    return f"job-{job_id}-highlight-{rank:02d}-{start_ms}-{end_ms}-vertical.mp4"


@app.command("highlight-reframe")
def highlight_reframe(
    job_id: Annotated[int, typer.Argument(help="Job ID to reframe a clip from.")],
    rank: Annotated[
        int,
        typer.Option(
            "--rank", help="Which ranked highlight-scan candidate to reframe (1 = top-ranked)."
        ),
    ] = 1,
    horizontal_offset: Annotated[
        float,
        typer.Option(
            "--horizontal-offset",
            help=(
                "Static horizontal crop position in [0.0, 1.0] "
                "(0.0=left edge, 0.5=centered, 1.0=right edge). No dynamic/subject "
                "tracking - this MVP uses one fixed position for the whole clip."
            ),
        ),
    ] = 0.5,
) -> None:
    """Cut one ranked highlight candidate from a job's local source video
    into a new local 9:16 vertical MP4 file, using a static deterministic
    crop (no dynamic/subject tracking in this iteration). Reuses the same
    deterministic highlight analysis as highlight-scan/highlight-cut (same
    configs, same ranking) so --rank N always matches highlight-scan's
    rank N exactly.

    This never claims the job, never increments attempts, never changes
    job status, never touches rights state, never calls an LLM or
    YouTube, never uploads, and never runs the render/publish pipeline.
    The only database interaction is a single read via
    JobRepository.get_job(). The original source file is never modified,
    moved, renamed, or deleted, and an existing output file is never
    overwritten.
    """
    if rank < 1:
        raise typer.BadParameter("--rank must be >= 1.")

    job, video_path = _load_rights_confirmed_local_job(job_id)

    try:
        _scenes, selected = _run_highlight_analysis(video_path, rank)
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if len(selected) < rank:
        raise typer.BadParameter(
            f"Job {job_id} only has {len(selected)} candidate(s) after overlap "
            f"suppression; --rank {rank} is out of range."
        )
    candidate = selected[rank - 1]

    settings = Settings()  # type: ignore[call-arg]
    output_dir = settings.work_dir / "highlights"
    filename = _highlight_reframe_filename(
        job_id, rank, candidate.start_seconds, candidate.end_seconds
    )
    output_path = output_dir / filename

    try:
        result = reframe_to_vertical(
            video_path,
            output_path,
            candidate.start_seconds,
            candidate.end_seconds,
            horizontal_offset_ratio=horizontal_offset,
        )
    except VerticalReframeError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Job {job_id}: {job['source_title']}")
    typer.echo(f"Rank: {rank}")
    typer.echo(f"Source path: {video_path}")
    typer.echo(f"Start: {result.start_seconds:.1f}s")
    typer.echo(f"End: {result.end_seconds:.1f}s")
    typer.echo(f"Duration: {result.duration_seconds:.1f}s")
    typer.echo(f"Score: {candidate.score:.3f}")
    typer.echo(f"Crop: {result.crop_width}x{result.crop_height} at x={result.crop_x1}")
    typer.echo(f"Output path: {result.output_path}")


def _highlight_caption_filename(
    job_id: int, rank: int, start_seconds: float, end_seconds: float
) -> str:
    start_ms = round(start_seconds * 1000)
    end_ms = round(end_seconds * 1000)
    return f"job-{job_id}-highlight-{rank:02d}-{start_ms}-{end_ms}-vertical-captioned.mp4"


@app.command("highlight-caption")
def highlight_caption(
    job_id: Annotated[int, typer.Argument(help="Job ID to caption a clip from.")],
    rank: Annotated[
        int,
        typer.Option(
            "--rank", help="Which ranked highlight-scan candidate to caption (1 = top-ranked)."
        ),
    ] = 1,
    horizontal_offset: Annotated[
        float,
        typer.Option(
            "--horizontal-offset",
            help=(
                "Static horizontal crop position in [0.0, 1.0] "
                "(0.0=left edge, 0.5=centered, 1.0=right edge), same as highlight-reframe."
            ),
        ),
    ] = 0.5,
    model_size: Annotated[
        str,
        typer.Option(
            "--model-size",
            help="faster-whisper model size (e.g. tiny, base, small, medium). CPU/int8 only.",
        ),
    ] = "base",
) -> None:
    """Cut one ranked highlight candidate from a job's local source video,
    crop it to a static 9:16 vertical frame (same as highlight-reframe),
    transcribe its audio locally with faster-whisper (CPU/int8, no cloud
    ASR), and burn the transcribed words as readable captions onto a new
    local MP4. Captions are the ASR's own words, only segmented for
    readability - never rewritten, translated, or summarized.

    This never claims the job, never increments attempts, never changes
    job status, never touches rights state, never calls an LLM or
    YouTube, never uploads, and never runs the render/publish pipeline.
    The only database interaction is a single read via
    JobRepository.get_job(). The original source file is never modified,
    moved, renamed, or deleted, and an existing output file is never
    overwritten.
    """
    if rank < 1:
        raise typer.BadParameter("--rank must be >= 1.")

    job, video_path = _load_rights_confirmed_local_job(job_id)

    try:
        _scenes, selected = _run_highlight_analysis(video_path, rank)
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if len(selected) < rank:
        raise typer.BadParameter(
            f"Job {job_id} only has {len(selected)} candidate(s) after overlap "
            f"suppression; --rank {rank} is out of range."
        )
    candidate = selected[rank - 1]

    settings = Settings()  # type: ignore[call-arg]
    output_dir = settings.work_dir / "highlights"
    output_dir.mkdir(parents=True, exist_ok=True)
    captioned_filename = _highlight_caption_filename(
        job_id, rank, candidate.start_seconds, candidate.end_seconds
    )
    captioned_output_path = output_dir / captioned_filename
    if captioned_output_path.exists():
        raise typer.BadParameter(
            f"Output file already exists, refusing to overwrite: {captioned_output_path}"
        )

    with tempfile.TemporaryDirectory(dir=output_dir) as tmp_dir_name:
        intermediate_path = Path(tmp_dir_name) / "reframed.mp4"
        try:
            reframe_result = reframe_to_vertical(
                video_path,
                intermediate_path,
                candidate.start_seconds,
                candidate.end_seconds,
                horizontal_offset_ratio=horizontal_offset,
            )
        except VerticalReframeError as exc:
            raise typer.BadParameter(str(exc)) from exc

        try:
            recognizer = FasterWhisperRecognizer(model_size=model_size)
            segments = recognizer.transcribe(intermediate_path)
        except TranscriptionError as exc:
            raise typer.BadParameter(str(exc)) from exc

        try:
            caption_result = burn_captions(intermediate_path, captioned_output_path, segments)
        except CaptionError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Job {job_id}: {job['source_title']}")
    typer.echo(f"Rank: {rank}")
    typer.echo(f"Source path: {video_path}")
    typer.echo(f"Start: {reframe_result.start_seconds:.1f}s")
    typer.echo(f"End: {reframe_result.end_seconds:.1f}s")
    typer.echo(f"Duration: {reframe_result.duration_seconds:.1f}s")
    typer.echo(f"Score: {candidate.score:.3f}")
    typer.echo(
        f"Crop: {reframe_result.crop_width}x{reframe_result.crop_height} "
        f"at x={reframe_result.crop_x1}"
    )
    typer.echo(f"Caption segments: {caption_result.segment_count}")
    typer.echo(f"Output path: {caption_result.output_path}")


# Literal path per this phase's brief - deliberately not Settings.work_dir
# (which itself defaults to the same "work" directory), so this command
# never constructs Settings()/JobRepository and stays usable even when the
# queue database is completely unreachable.
_DEFAULT_PACKAGE_ROOT = Path("work") / "ready"


def _print_quality_checks(checks: list[Any]) -> None:
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        typer.echo(f"  [{status}] {check.name}: {check.detail}")


@app.command("short-qc")
def short_qc(
    path: Annotated[Path, typer.Argument(help="Local media file to quality-check.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON instead of text.")
    ] = False,
) -> None:
    """Inspect one local media artifact and decide PASS or FAIL with an
    explicit reason per check (existence, decodability, duration bounds,
    9:16 aspect ratio, dimensions, FPS, audio presence, black start/end
    frames, sampled-frame decode integrity, metadata validity).

    Read-only: never modifies or deletes the inspected file. Requires no
    database connection - a local artifact must be inspectable even if
    Neon is unavailable. Exit code 0 on PASS, non-zero on FAIL.
    """
    result = run_quality_gate(path)

    if as_json:
        payload = {
            "path": str(path),
            "passed": result.passed,
            "checks": [dataclasses.asdict(c) for c in result.checks],
            "media": dataclasses.asdict(result.media),
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Path: {path}")
        typer.echo("PASS" if result.passed else "FAIL")
        _print_quality_checks(result.checks)

    if not result.passed:
        raise typer.Exit(code=1)


@app.command("short-package")
def short_package(
    path: Annotated[Path, typer.Argument(help="Local media file to package as publish-ready.")],
) -> None:
    """Run the exact same quality gate as short-qc against a local media
    artifact; if it fails, refuse to package and list every failed check.
    If it passes, copy the artifact (never move/modify/delete the
    original) plus a JSON manifest (SHA-256, byte size, media metadata,
    quality-gate check results, package timestamp - no secrets, no OAuth
    tokens) into a new directory under work/ready/. Fails safely (creates
    nothing) rather than silently overwriting an existing package.

    Requires no database connection and never uploads anything.
    """
    try:
        result = package_short(path, _DEFAULT_PACKAGE_ROOT)
    except PackagingError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Source path: {path}")
    typer.echo(f"Package directory: {result.package_dir}")
    typer.echo(f"Packaged artifact: {result.packaged_video_path}")
    typer.echo(f"Manifest: {result.manifest_path}")
    typer.echo(f"SHA-256: {result.manifest['sha256']}")


@app.command("youtube-publish-package")
def youtube_publish_package(
    package_dir: Annotated[
        Path, typer.Argument(help="A Phase 8D work/ready/<package>/ directory to publish.")
    ],
    title: Annotated[
        str,
        typer.Option(
            "--title", help="Video title. Manual, operator-supplied - never LLM-generated."
        ),
    ],
    description: Annotated[
        str,
        typer.Option(
            "--description",
            help="Video description. Manual, operator-supplied - never LLM-generated.",
        ),
    ],
    tags: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Video tag (repeatable). Manual, operator-supplied."),
    ] = None,
    execute_upload: Annotated[
        bool,
        typer.Option(
            "--execute-private-upload",
            help=(
                "Actually perform the upload (PRIVATE ONLY - hard-coded, not configurable "
                "here). Without this flag the command only validates and never touches "
                "YouTube."
            ),
        ),
    ] = False,
) -> None:
    """Publish one validated Phase 8D package to YouTube as a PRIVATE video.

    privacy_status is hard-coded to "private" - there is no option on this
    command capable of selecting public or unlisted.

    DEFAULT BEHAVIOR IS DRY RUN: validates package integrity (manifest,
    byte size, SHA-256, path-traversal-safe artifact resolution), re-runs
    the Phase 8D quality gate fresh, and validates title/description/tags
    - all with zero network I/O. It never constructs YouTubeAuth or
    YouTubeUploader, never loads an OAuth token, and never calls YouTube.
    Exit code 0 on a passing dry run; non-zero with an explicit reason on
    any validation failure.

    Only with --execute-private-upload does this command touch YouTube:
    it revalidates the package, requires youtube_expected_channel_id to be
    configured, loads existing OAuth credentials non-interactively (no
    browser - if missing, it fails and tells the operator to run
    `robin-engine youtube-auth` separately) and verifies the authenticated
    channel exactly matches the expected channel ID before ever
    constructing an uploader. A local upload_attempt.json /
    upload_receipt.json pair in the package directory guards against a
    duplicate upload (no --force option); if the uploader raises after
    upload execution has begun, the attempt marker is intentionally left
    in place for operator reconciliation rather than being auto-cleared
    for a retry, since the remote upload may have already succeeded.

    Never claims a queue job, never touches JobRepository/rights/job
    status, never calls pipeline.run_once() or ContentEngine.
    """
    clean_tags = tags or []

    if not execute_upload:
        try:
            result = dry_run(package_dir, title, description, clean_tags)
        except PublishingError as exc:
            raise typer.BadParameter(str(exc)) from exc

        media = result.validation.quality_gate.media
        typer.echo("DRY RUN PASS")
        typer.echo(f"Package SHA-256: {result.validation.manifest.get('sha256')}")
        typer.echo(
            f"Media: duration={media.duration_seconds}s, {media.width}x{media.height}, "
            f"fps={media.fps}, audio={media.has_audio}"
        )
        typer.echo(f"Title: {result.metadata.title}")
        typer.echo(f"Tag count: {len(result.metadata.tags)}")
        typer.echo("Privacy: private")
        return

    settings = Settings()  # type: ignore[call-arg]
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)

    # privacy_status="private" is enforced inside execute_private_upload()
    # itself, not here - YouTubeUploader is passed as a plain constructor
    # so this call site has no opportunity to influence the privacy value.
    try:
        upload_result = execute_private_upload(
            package_dir, title, description, clean_tags, settings, auth, YouTubeUploader
        )
    except PublishingError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("UPLOAD SUCCESS")
    typer.echo(f"YouTube video ID: {upload_result.youtube_id}")
    typer.echo(f"Privacy: {upload_result.privacy_status}")


@app.command()
def version() -> None:
    """Print the installed engine version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
