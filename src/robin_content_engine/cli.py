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
from .ai_logic import ContentGenerator
from .captioner import CaptionError, burn_captions
from .capture_scan import CaptureScanError, scan_captures
from .channel_import import ChannelImportError, import_video_as_short, list_long_videos
from .channel_metadata import ChannelMetadataError, ChannelMetadataFixer
from .channel_repository import ChannelRepository
from .clip_cutter import ClipCutError, cut_clip
from .clip_selector import (
    ClipSelectionError,
    HighlightCandidate,
    WindowSelectorConfig,
    generate_candidate_windows,
    suppress_overlaps,
)
from .config import APP_ROOT, Settings
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
from .production_runner import (
    ProductionRunError,
    build_production_metadata,
    find_ambiguous_packages,
    production_status,
    reconcile_ambiguous_uploads,
    run_production,
    run_production_once,
)
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


@app.command("production-run")
def production_run(
    job_id: Annotated[
        int, typer.Argument(help="Job ID to run through the full local production pipeline.")
    ],
    rank: Annotated[
        int,
        typer.Option(
            "--rank", help="Which ranked highlight-scan candidate to produce (1 = top-ranked)."
        ),
    ] = 1,
    horizontal_offset: Annotated[
        float,
        typer.Option(
            "--horizontal-offset",
            help="Static horizontal crop position in [0.0, 1.0], same as highlight-reframe.",
        ),
    ] = 0.5,
    model_size: Annotated[
        str,
        typer.Option(
            "--model-size",
            help="faster-whisper model size (e.g. tiny, base, small, medium). CPU/int8 only.",
        ),
    ] = "base",
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            help=(
                "Video title. Only needed if you also want to publish (dry-run by default) "
                "after a passing quality gate + package. Manual, operator-supplied - never "
                "LLM-generated."
            ),
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help="Video description. Required together with --title to publish.",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Video tag (repeatable). Manual, operator-supplied."),
    ] = None,
    execute_upload: Annotated[
        bool,
        typer.Option(
            "--execute-private-upload",
            help=(
                "After a passing quality gate + package, also perform the real PRIVATE-ONLY "
                "YouTube upload, exactly as youtube-publish-package does. Requires --title "
                "and --description. Without this flag, providing --title/--description only "
                "runs the zero-network-I/O publish dry-run validation."
            ),
        ),
    ] = False,
) -> None:
    """Run one job/rank through every already-proven local production
    stage in a single command: highlight analysis, 9:16 reframe, local
    ASR + caption burn-in (falling back to an uncaptioned artifact if no
    speech is detected - not a failure), the Phase 8D quality gate, and
    Phase 8D packaging. Optionally, if --title/--description are given,
    also validates (or, with --execute-private-upload, actually performs)
    a Phase 9A PRIVATE-ONLY YouTube publish of the resulting package -
    reusing publishing.py's dry_run()/execute_private_upload() exactly as
    youtube-publish-package does, with no CLI option able to select
    public/unlisted.

    Resumable: re-running this command for the same job/rank reuses any
    already-completed reframe/caption/package outputs rather than
    redoing the (expensive) work.

    Never claims the job, never increments attempts, never changes job
    status or rights state, never calls an LLM. The only database
    interaction is a single read via JobRepository.get_job(). The
    original source file is never modified, moved, renamed, or deleted,
    and no existing output is ever silently overwritten.
    """
    if title is not None and description is None:
        raise typer.BadParameter("--description is required when --title is given.")
    if description is not None and title is None:
        raise typer.BadParameter("--title is required when --description is given.")
    if execute_upload and title is None:
        raise typer.BadParameter("--title and --description are required with "
                                  "--execute-private-upload.")

    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)

    try:
        result = run_production(
            job_id,
            rank,
            repository,
            settings,
            horizontal_offset_ratio=horizontal_offset,
            model_size=model_size,
        )
    except ProductionRunError as exc:
        raise typer.BadParameter(str(exc)) from exc

    _echo_production_result(result)

    if not result.quality_gate.passed:
        raise typer.Exit(code=1)

    assert result.package is not None
    typer.echo(f"Package: {result.package.package_dir}")

    if title is None:
        return

    clean_tags = tags or []

    if not execute_upload:
        try:
            dry_result = dry_run(result.package.package_dir, title, description or "", clean_tags)
        except PublishingError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo("PUBLISH DRY RUN PASS")
        typer.echo(f"Title: {dry_result.metadata.title}")
        typer.echo(f"Tag count: {len(dry_result.metadata.tags)}")
        typer.echo("Privacy: private")
        return

    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    try:
        upload_result = execute_private_upload(
            result.package.package_dir,
            title,
            description or "",
            clean_tags,
            settings,
            auth,
            YouTubeUploader,
        )
    except PublishingError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("UPLOAD SUCCESS")
    typer.echo(f"YouTube video ID: {upload_result.youtube_id}")
    typer.echo(f"Privacy: {upload_result.privacy_status}")


def _echo_production_result(result: Any) -> None:
    typer.echo(f"Job {result.job_id}: {result.source_title}")
    typer.echo(f"Rank: {result.rank}")
    typer.echo(
        f"Window: {result.start_seconds:.1f}s - {result.end_seconds:.1f}s "
        f"(score={result.candidate_score:.3f})"
    )
    if result.has_captions:
        typer.echo(f"Captions: yes ({result.caption_segment_count} segments)")
    else:
        typer.echo("Captions: no speech detected - using uncaptioned vertical artifact")
    typer.echo(f"Final artifact: {result.final_video_path}")
    typer.echo("Quality gate: PASS" if result.quality_gate.passed else "Quality gate: FAIL")
    _print_quality_checks(result.quality_gate.checks)


@app.command("production-run-once")
def production_run_once_command(
    horizontal_offset: Annotated[
        float,
        typer.Option(
            "--horizontal-offset",
            help="Static horizontal crop position in [0.0, 1.0], same as highlight-reframe.",
        ),
    ] = 0.5,
    model_size: Annotated[
        str,
        typer.Option(
            "--model-size",
            help="faster-whisper model size (e.g. tiny, base, small, medium). CPU/int8 only.",
        ),
    ] = "base",
    execute_upload: Annotated[
        bool,
        typer.Option(
            "--execute-private-upload",
            help=(
                "After a passing quality gate + package, also perform the real PRIVATE-ONLY "
                "YouTube upload. Without this flag, a zero-network-I/O publish dry-run "
                "validation runs instead."
            ),
        ),
    ] = False,
) -> None:
    """The operational Robin runner: scan the configured local capture
    directory for new gameplay recordings (idempotent registration,
    NEVER auto-confirming rights - reuses capture-scan unmodified),
    then automatically and deterministically select AT MOST ONE eligible
    local job (oldest job id first) and run it through the full local
    production pipeline - highlight analysis, 9:16 reframe, local ASR +
    caption burn-in (or an uncaptioned fallback if the clip has no
    detected speech), the Phase 8D quality gate, and Phase 8D
    packaging - followed by a publish step using fixed, deterministic,
    truthful metadata (no LLM, no TTS, no operator input required for
    normal operation).

    Eligibility mirrors the real queue-processing contract: status ==
    "pending", rights_confirmed == True, a local source_path, and no
    youtube_id already recorded. This deliberately excludes "uploaded",
    "rendered", "processing", "quarantined", and "failed" jobs - such a
    job requires the existing explicit operator retry path (rights-
    approve / a manual requeue) to become "pending" again before this
    command will ever touch it automatically. A cheap, read-only,
    filesystem-only precheck (no media processing) additionally skips a
    candidate with a pre-existing upload_receipt.json (already
    published) or upload_attempt.json without one (ambiguous - operator
    reconciliation required, never auto-retried) before selecting the
    next candidate; once a candidate is actually selected, at most ONE
    is ever run in a single invocation - a quality-gate, package, or
    processing failure on the selected job ends that invocation rather
    than falling through to try another job.

    Prints "NO ELIGIBLE JOB" and exits 0 if there is nothing to do - an
    empty queue is a normal outcome, not a failure. A selected job that
    fails DETERMINISTICALLY (same source and analysis would fail
    identically every time - missing source, analysis failure, quality-
    gate failure, a package that fails validation after being freshly
    rebuilt) is quarantined with the failure reason recorded and this
    command prints the reason and exits non-zero; a transient failure
    also exits non-zero (visible in the scheduled task's log) and the
    job is simply retried on the next invocation.

    Publishing defaults to a zero-network-I/O dry run; only
    --execute-private-upload performs a real write, and it is always
    PRIVATE ONLY (no CLI option can select public/unlisted) with at most
    ONE upload attempt per invocation - this command processes at most
    one job, and publishing.execute_private_upload()'s own atomic
    duplicate-upload guard makes a second upload attempt on the same
    package impossible regardless.

    Never claims a job, never increments attempts, never calls an LLM or
    TTS, never uses the legacy ContentEngine/render-upload pipeline. The
    only database interactions are the same reads capture-scan/highlight-
    scan already make (list_jobs(), get_job()) plus capture-scan's own
    INSERT-only registration of newly discovered captures with
    rights_confirmed=false - and, on a deterministic failure of the
    selected job only, the quarantine UPDATE that records the failure
    reason and takes the job out of the automatic queue (see the failure
    classification above). Never an UPDATE to any other row, and never
    on the success path.
    """
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)

    try:
        once_result = run_production_once(
            repository,
            settings,
            horizontal_offset_ratio=horizontal_offset,
            model_size=model_size,
        )
    except (CaptureScanError, ProductionRunError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    scan = once_result.capture_scan
    typer.echo("Capture scan completed.")
    typer.echo(f"Directory: {scan.directory}")
    typer.echo(f"Videos discovered: {scan.videos_discovered}")
    typer.echo(f"New captures registered: {scan.new_registered}")

    for skipped in once_result.skipped:
        typer.echo(f"Skipped job {skipped.job_id}: {skipped.reason}")

    if once_result.selected_job_id is None:
        typer.echo("NO ELIGIBLE JOB")
        return

    if once_result.terminal_failure is not None:
        failure = once_result.terminal_failure
        if once_result.run is not None:
            _echo_production_result(once_result.run)
        typer.echo(
            f"Job {failure.job_id} failed permanently (deterministic outcome) and was "
            f"quarantined so it will not be retried automatically: {failure.reason}"
        )
        raise typer.Exit(code=1)

    result = once_result.run
    assert result is not None
    _echo_production_result(result)

    if not result.quality_gate.passed:
        raise typer.Exit(code=1)

    assert result.package is not None
    typer.echo(f"Package: {result.package.package_dir}")

    title, description, tags = build_production_metadata(result.source_title, settings)
    typer.echo(f"Title: {title}")

    if not execute_upload:
        try:
            dry_result = dry_run(result.package.package_dir, title, description, tags)
        except PublishingError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo("PUBLISH DRY RUN PASS")
        typer.echo(f"Tag count: {len(dry_result.metadata.tags)}")
        typer.echo("Privacy: private")
        return

    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    try:
        upload_result = execute_private_upload(
            result.package.package_dir, title, description, tags, settings, auth, YouTubeUploader
        )
    except PublishingError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("UPLOAD SUCCESS")
    typer.echo(f"YouTube video ID: {upload_result.youtube_id}")
    typer.echo(f"Privacy: {upload_result.privacy_status}")


@app.command("production-config")
def production_config_command() -> None:
    """Print the resolved runtime configuration roots this installation
    actually uses - the canonical application root, the .env file read,
    the work directory, the capture source directory, and the Python
    interpreter - so an operator (or the scheduled-task launcher) can
    verify that Settings resolved against the intended production
    repository and not whatever directory the process happened to start
    from.

    Pure reads. Never prints secrets (no database URL, no API keys, no
    OAuth token paths or contents).
    """
    settings = Settings()  # type: ignore[call-arg]
    import sys

    typer.echo(f"Application root: {APP_ROOT}")
    typer.echo(f"Config file: {APP_ROOT / '.env'}")
    typer.echo(f"Work directory: {settings.work_dir}")
    typer.echo(f"Capture source directory: {settings.capture_source_dir}")
    typer.echo(f"Python executable: {sys.executable}")
    typer.echo(f"Source root: {APP_ROOT / 'src'}")


@app.command("production-reconcile")
def production_reconcile_command() -> None:
    """Resolve packages stuck in an ambiguous upload state by asking
    YouTube itself.

    A package is "ambiguous" when an upload_attempt.json marker exists
    but no upload_receipt.json ever confirmed the outcome (the remote
    upload may have succeeded even though the response was lost). This
    command fetches the authenticated channel's current PRIVATE upload
    inventory and, for each ambiguous package, looks for exactly one
    video whose published_at matches the attempt marker's started_at
    (within a 15-minute tolerance). An exactly-one match unambiguously
    identifies the upload: the receipt is written from the marker + the
    matched video's data (atomic, same as a confirmed upload) and the
    attempt marker is removed, moving the package to "published".

    Zero or multiple candidates are NOT resolvable from the inventory
    alone - nothing is written, nothing is guessed, and the operator
    must look at YouTube manually. Exit code 0 only when every
    ambiguous package was resolved; non-zero when any remains.

    Never touches the database, never uploads, never deletes anything
    remotely.
    """
    settings = Settings()  # type: ignore[call-arg]
    if not find_ambiguous_packages():
        typer.echo("No ambiguous upload states found.")
        return

    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    sync = YouTubeChannelSync(auth, settings.youtube_expected_channel_id)

    outcomes = reconcile_ambiguous_uploads(sync)

    unresolved = 0
    for outcome in outcomes:
        marker = "RESOLVED" if outcome.resolved else "UNRESOLVED"
        typer.echo(
            f"{marker} {outcome.package_dir}: {outcome.detail}"
        )
        unresolved += 0 if outcome.resolved else 1

    if unresolved:
        raise typer.Exit(1)


@app.command("production-status")
def production_status_command(
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON instead of text.")
    ] = False,
) -> None:
    """Read-only status report across every job: awaiting rights,
    rejected (explicitly operator-rejected/quarantined - never
    "awaiting rights", per the same reviewable-state predicate
    JobRepository.list_pending_rights_review() itself uses), rights-
    approved eligible, processing (local production started), packaged,
    uploaded (private), and ambiguous upload states (a prior upload
    attempt whose outcome is unknown - never auto-retried).

    Pure reads only - no database write, no network I/O, no video
    decoding (local state is derived entirely from deterministic
    filename globs and marker-file existence, matching the same
    filenames run_production()/execute_private_upload() already use).
    """
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)

    status = production_status(repository, settings)

    if as_json:
        payload = {
            "awaiting_rights": status.awaiting_rights,
            "rejected": status.rejected,
            "rights_approved_eligible": status.rights_approved_eligible,
            "processing": status.processing,
            "packaged": status.packaged,
            "uploaded_private": status.uploaded_private,
            "ambiguous": status.ambiguous,
            "inactive": status.inactive,
            "jobs": [dataclasses.asdict(j) for j in status.jobs],
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"Awaiting rights: {status.awaiting_rights}")
    typer.echo(f"Rejected: {status.rejected}")
    typer.echo(f"Rights-approved eligible: {status.rights_approved_eligible}")
    typer.echo(f"Processing: {status.processing}")
    typer.echo(f"Packaged: {status.packaged}")
    typer.echo(f"Uploaded (private): {status.uploaded_private}")
    typer.echo(f"Ambiguous upload state: {status.ambiguous}")
    typer.echo(f"Inactive: {status.inactive}")


@app.command("channel-long-videos")
def channel_long_videos_command(
    min_seconds: Annotated[
        int, typer.Option("--min-seconds", help="Only list videos at least this long (s).")
    ] = 60,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Maximum number of videos to list."),
    ] = 20,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """List the channel's long-form (non-Short) videos from the stored
    youtube-videos snapshot as candidates for `channel-import` Short
    extraction. Pure read - no network I/O."""
    settings = Settings()  # type: ignore[call-arg]
    videos = list_long_videos(settings, min_seconds=min_seconds, limit=limit)

    if as_json:
        typer.echo(json.dumps(videos, ensure_ascii=False, indent=2))
        return

    if not videos:
        typer.echo("No long videos found in the snapshot. Run 'robin-engine youtube-sync' first.")
        return
    typer.echo(f"Long videos (>= {min_seconds}s): {len(videos)}")
    for video in videos:
        minutes = video["duration_seconds"] // 60
        seconds = video["duration_seconds"] % 60
        typer.echo(
            f"  {video['video_id']}  {minutes}:{seconds:02d}  "
            f"{video['view_count'] or 0} views  {video['title'][:60]}"
        )


@app.command("channel-import")
def channel_import_command(
    video_ids: Annotated[
        list[str],
        typer.Argument(
            help="One or more channel video IDs to download and turn into Shorts.",
        ),
    ],
    rank: Annotated[
        int,
        typer.Option("--rank", help="Which ranked highlight candidate to produce (1 = top)."),
    ] = 1,
    model_size: Annotated[
        str,
        typer.Option("--model-size", help="faster-whisper model size for captioning."),
    ] = "base",
    min_seconds: Annotated[
        float | None,
        typer.Option("--min-seconds", help="Highlight window minimum length (s)."),
    ] = None,
    max_seconds: Annotated[
        float | None,
        typer.Option("--max-seconds", help="Highlight window maximum length (s)."),
    ] = None,
    no_upload: Annotated[
        bool,
        typer.Option("--no-upload", help="Download + process but do not upload to YouTube."),
    ] = False,
) -> None:
    """Download own-channel long videos (via yt-dlp), cut each one's top
    highlight into a 9:16 Short with captions, and - unless --no-upload -
    publish it to the channel (privacy follows YOUTUBE_PUBLIC_AFTER_UPLOAD
    and YOUTUBE_AI_METADATA). The imported footage is registered as a
    rights-confirmed queue job because it is the channel's own upload.

    Highlight length defaults to HIGHLIGHT_MIN_SECONDS/HIGHLIGHT_MAX_SECONDS
    from configuration; override per run with --min-seconds/--max-seconds.

    Requires the optional yt-dlp dependency for downloading.
    """
    settings = Settings()  # type: ignore[call-arg]
    repository = JobRepository(settings.database_url, settings.max_job_attempts)
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)

    selector_config = WindowSelectorConfig(
        min_clip_seconds=min_seconds or settings.highlight_min_seconds,
        max_clip_seconds=max_seconds or settings.highlight_max_seconds,
    )

    for video_id in video_ids:
        typer.echo(f"=== Importing {video_id} ===")
        try:
            job_id, result = import_video_as_short(
                video_id,
                repository,
                settings,
                rank=rank,
                model_size=model_size,
                selector_config=selector_config,
            )
        except ChannelImportError as exc:
            raise typer.BadParameter(str(exc)) from exc

        _echo_production_result(result)
        typer.echo(f"Queued/processed as job {job_id}.")

        if no_upload or not result.quality_gate.passed or result.package is None:
            continue

        title, description, tags = build_production_metadata(result.source_title, settings)
        typer.echo(f"Title: {title}")
        try:
            upload_result = execute_private_upload(
                result.package.package_dir,
                title,
                description,
                tags,
                settings,
                auth,
                YouTubeUploader,
            )
        except PublishingError as exc:
            raise typer.BadParameter(str(exc)) from exc

        typer.echo("UPLOAD SUCCESS")
        typer.echo(f"YouTube video ID: {upload_result.youtube_id}")
        typer.echo(f"Privacy: {upload_result.privacy_status}")


@app.command("channel-metadata-fix")
def channel_metadata_fix_command(
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Actually write metadata to YouTube (default: plan only)."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Maximum videos to add to the plan this run."),
    ] = None,
    max_updates: Annotated[
        int | None,
        typer.Option(
            "--max-updates",
            help="Maximum YouTube videos.update() calls this run (quota guard).",
        ),
    ] = None,
    quota_budget: Annotated[
        int | None,
        typer.Option(
            "--quota-budget",
            help="Stop once this many YouTube quota units are consumed "
            "(a videos.update costs 1600 units).",
        ),
    ] = None,
    game_only: Annotated[
        bool,
        typer.Option("--game-only", help="Only fix videos whose game can be detected."),
    ] = False,
    video_id: Annotated[
        list[str] | None,
        typer.Option("--video-id", help="Restrict to specific video IDs (repeatable)."),
    ] = None,
    show_status: Annotated[
        bool, typer.Option("--status", help="Print the persisted plan status and exit.")
    ] = False,
    reset: Annotated[
        bool,
        typer.Option("--reset", help="Clear the persisted metadata plan and exit."),
    ] = False,
) -> None:
    """Fix titles/descriptions/tags across the channel's videos using the
    AI Arabic metadata generator.

    Resumable and quota-aware: discoveries, generated metadata and applied
    state are persisted in work/metadata_plan.json, so an interrupted or
    quota-limited run resumes where it left off instead of re-burning
    DeepSeek calls and YouTube quota. Generated metadata passes a
    deterministic safety validation (bounds + banned clickbait/claim
    phrases) before it can reach YouTube.

    Without --apply this only builds the plan (and prints it). With
    --apply it performs videos.update() calls, bounded by --max-updates /
    --quota-budget so a scheduled run can chip away at a large backlog
    without exhausting the daily API quota.
    """
    settings = Settings()  # type: ignore[call-arg]
    generator = ContentGenerator(
        settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model
    )
    auth = YouTubeAuth(settings.youtube_client_secret_file, settings.youtube_token_file)
    fixer = ChannelMetadataFixer(settings, auth, generator)

    if reset:
        fixer.plan.path.unlink(missing_ok=True)
        typer.echo("Metadata plan cleared.")
        return

    if show_status:
        pending = fixer.plan.pending()
        typer.echo(f"Plan file: {fixer.plan.path}")
        typer.echo(f"Pending: {len(pending)}")
        typer.echo(f"Done: {fixer.plan.done_count()}")
        for entry in pending:
            state = "has-metadata" if entry.new_title else "needs-generation"
            typer.echo(f"  {entry.video_id} [{state}] {entry.old_title[:50]}")
        return

    discovered = fixer.discover(video_ids=video_id)
    if game_only:
        discovered = [entry for entry in discovered if entry.game]
    if limit is not None:
        discovered = discovered[:limit]

    typer.echo(f"Videos needing metadata fixes: {len(discovered)}")

    generated = 0
    failed_gen = 0
    for entry in fixer.plan.pending():
        if entry.new_title is not None:
            typer.echo(f"  {entry.video_id}: {entry.old_title[:40]!r} -> {entry.new_title!r}")
            continue
        try:
            fixer.generate_for(entry)
            generated += 1
            typer.echo(f"  {entry.video_id}: {entry.old_title[:40]!r} -> {entry.new_title!r}")
        except ChannelMetadataError as exc:
            failed_gen += 1
            typer.echo(f"  generation failed for {entry.video_id}: {exc}")

    typer.echo(f"Generated: {generated}, failed: {failed_gen}")

    if not apply:
        typer.echo("Plan built (not applied). Pass --apply to write to YouTube.")
        return

    applied, failed, failures = fixer.apply(max_updates=max_updates, quota_budget=quota_budget)
    typer.echo(f"Applied: {applied}, failed: {failed}")
    for video_id_, err in failures:
        typer.echo(f"  {video_id_}: {err}")


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
