from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .captioner import CaptionError, burn_captions
from .capture_scan import CaptureScanResult, scan_captures
from .clip_selector import (
    ClipSelectionError,
    HighlightCandidate,
    WindowSelectorConfig,
    generate_candidate_windows,
    suppress_overlaps,
)
from .config import Settings
from .database import AUTO_QUARANTINE_REASON, JobRepository
from .highlight_features import (
    FeatureExtractionError,
    compute_scene_density,
    extract_audio_activity,
    extract_motion_activity,
    generate_time_windows,
)
from .highlight_scoring import score_windows
from .publishing import PackageValidation, PublishingError, validate_package
from .quality_gate import (
    PackagingError,
    QualityGateConfig,
    QualityGateResult,
    package_short,
    run_quality_gate,
)
from .scene_detector import SceneBoundary, SceneDetectionError, detect_scenes
from .transcription import FasterWhisperRecognizer, TranscriptionError
from .vertical_reframe import VerticalReframeError, reframe_to_vertical

# Same value as cli.py's own module-level constant (not CLI-exposed there
# either) - kept in sync deliberately, not imported, for the same
# already-proven-code-safety reason documented on the two helpers below.
_HIGHLIGHT_WINDOW_SECONDS = 1.0

# Literal path matching cli.py's own _DEFAULT_PACKAGE_ROOT (itself
# deliberately not Settings.work_dir-relative) - duplicated rather than
# imported so this module has no dependency on cli.py at all.
_DEFAULT_PACKAGE_ROOT = Path("work") / "ready"

_NO_SPEECH_MARKER = "No non-empty transcript segments"

# Local upload-state marker filenames - identical literals to
# publishing.py's own (private) _ATTEMPT_FILENAME/_RECEIPT_FILENAME
# constants, duplicated here (not imported) for the same
# already-proven-code-safety reason as the helpers below. These are pure
# read-only filesystem checks - this module never creates or deletes
# either file itself; that remains publishing.py's exclusive
# responsibility.
_UPLOAD_ATTEMPT_FILENAME = "upload_attempt.json"
_UPLOAD_RECEIPT_FILENAME = "upload_receipt.json"


class ProductionRunError(Exception):
    """Raised for any Production Runner failure: missing/unconfirmed job,
    analysis failure, reframe failure, a genuine (non-no-speech)
    captioning failure, an existing-package validation failure (corrupt/
    stale/tampered package), or a packaging failure. A clip with no
    detected speech is NOT an error - see run_production()'s caption-
    fallback handling."""


# ---------------------------------------------------------------------------
# Shared read-only job lookup / highlight analysis (duplicated from cli.py)
# ---------------------------------------------------------------------------


def _validate_job_and_source(job: dict[str, Any]) -> Path:
    """Pure validation of an ALREADY-LOADED job row - performs no
    repository access of its own. Used both by
    _load_rights_confirmed_local_job() (right after its own single fetch)
    and directly by run_production_once() (against a row already in hand
    from its own single list_jobs() snapshot, so selecting a candidate
    never requires a second database round-trip). Raises
    ProductionRunError if rights aren't confirmed or the local source
    file doesn't exist."""
    job_id = job["id"]
    if not job["rights_confirmed"]:
        raise ProductionRunError(
            f"Job {job_id} does not have confirmed publishing rights "
            "(rights_confirmed=False). Run rights-approve first."
        )
    source_path = job.get("source_path")
    if not source_path:
        raise ProductionRunError(
            f"Job {job_id} has no local source_path to analyze "
            "(remote sources are not supported)."
        )
    video_path = Path(source_path)
    if not video_path.is_file():
        raise ProductionRunError(f"Source file does not exist: {video_path}")
    return video_path


def _load_rights_confirmed_local_job(
    job_id: int, repository: JobRepository
) -> tuple[dict[str, Any], Path]:
    """Read-only job lookup - exactly ONE repository.running() cycle,
    mirroring cli.py's own helper of the same name (used by highlight-
    scan/highlight-cut/highlight-reframe/highlight-caption) field-for-
    field. Duplicated here rather than imported from cli.py to avoid any
    risk of regressing those already-proven, already-shipped commands
    via a shared-code refactor - the tradeoff of a small amount of
    duplicated glue against touching code that has already carried a
    real production job through a real private YouTube upload. Never
    claims the job or mutates any state."""
    with repository.running():
        job = repository.get_job(job_id)

    if job is None:
        raise ProductionRunError(f"Job {job_id} not found.")
    video_path = _validate_job_and_source(job)
    return job, video_path


def _run_highlight_analysis(
    video_path: Path, top_n: int
) -> tuple[list[SceneBoundary], list[HighlightCandidate]]:
    """Mirrors cli.py's own helper of the same name field-for-field - see
    that docstring for the full rationale (deterministic scoring,
    suppress_overlaps() prefix-stability across top_n, read-only/no-DB-
    write). Duplicated for the same reason as
    _load_rights_confirmed_local_job above."""
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


def _reframed_filename(job_id: int, rank: int, start_seconds: float, end_seconds: float) -> str:
    """Identical scheme to cli.py's _highlight_reframe_filename() -
    intentionally, so a production-run and a manual highlight-reframe
    for the same job/rank produce (and can resume/reuse) the exact same
    file."""
    start_ms = round(start_seconds * 1000)
    end_ms = round(end_seconds * 1000)
    return f"job-{job_id}-highlight-{rank:02d}-{start_ms}-{end_ms}-vertical.mp4"


def _captioned_filename(job_id: int, rank: int, start_seconds: float, end_seconds: float) -> str:
    """Identical scheme to cli.py's _highlight_caption_filename() -
    intentionally, for the same interoperability/resumability reason."""
    start_ms = round(start_seconds * 1000)
    end_ms = round(end_seconds * 1000)
    return f"job-{job_id}-highlight-{rank:02d}-{start_ms}-{end_ms}-vertical-captioned.mp4"


# ---------------------------------------------------------------------------
# Deterministic automatic metadata - no LLM, no TTS, no operator input
# ---------------------------------------------------------------------------


def build_automatic_metadata(source_title: str) -> tuple[str, str]:
    """Fixed, deterministic, truthful metadata for production-run-once.
    Never an LLM call, never TTS, never requires operator input for
    normal automatic operation."""
    title = f"{source_title} — Highlight"
    description = "Automatically processed from operator-owned gameplay by Robin Content Engine."
    return title, description


# ---------------------------------------------------------------------------
# Core single-job orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionRunResult:
    job_id: int
    rank: int
    source_title: str
    candidate_score: float
    start_seconds: float
    end_seconds: float
    reframed_video_path: Path
    has_captions: bool
    caption_segment_count: int | None
    final_video_path: Path
    quality_gate: QualityGateResult
    package: PackageValidation | None


def _run_production_loaded_job(
    job: dict[str, Any],
    video_path: Path,
    rank: int,
    settings: Settings,
    *,
    horizontal_offset_ratio: float = 0.5,
    model_size: str = "base",
    quality_gate_config: QualityGateConfig | None = None,
    package_dest_root: Path | None = None,
) -> ProductionRunResult:
    """Orchestrate one already-loaded job/rank through every already-
    proven local stage - highlight analysis, 9:16 reframe, local ASR +
    caption burn-in, the Phase 8D quality gate, and Phase 8D packaging -
    reusing every underlying module unmodified. Does NOT publish; see
    publishing.py's dry_run()/execute_private_upload() for that, called
    separately by the CLI against this function's returned package
    directory.

    Performs ZERO repository access - job must already be loaded and
    validated (rights_confirmed, source_path existence) by the caller,
    e.g. via _load_rights_confirmed_local_job() or
    _validate_job_and_source(). This lets callers keep the database
    connection pool open for only as long as the lookup itself takes,
    never across the (potentially very long) media-processing stages
    below.

    Resumable by construction: each expensive stage's existing
    deterministic filename and refuse-to-overwrite behavior is used to
    skip already-completed work on a re-run, rather than introducing a
    new state-file format. The one ambiguous case - a reframed file
    exists but no captioned file does, e.g. from an interrupted prior
    run - is resolved conservatively by always re-attempting captioning
    against the existing reframed file (idempotent - the same audio
    always transcribes to the same result) rather than guessing whether
    the prior run had already determined "no speech".

    An existing package directory is NEVER blindly trusted: whether
    freshly packaged this call or found already on disk from a prior
    run, it is always validated via publishing.validate_package() (the
    same Phase 9 contract youtube-publish-package itself uses) before
    being returned - manifest well-formed, quality_gate_passed=true as
    recorded, byte size/SHA-256 matching, and the quality gate re-run
    fresh. A corrupt or stale existing package raises ProductionRunError
    rather than being silently reused.

    A clip with no detected speech falls back to using the reframed
    (uncaptioned) clip as the final artifact rather than failing the
    whole run - this is the one new behavior beyond pure orchestration
    this module introduces. Every other failure (analysis failure,
    reframe failure, a genuine transcription/caption-burn failure, or a
    quality-gate/packaging/package-validation failure) raises
    ProductionRunError with an explicit reason.

    Never touches JobRepository, never touches YouTube, never uploads.
    """
    job_id = job["id"]

    try:
        _scenes, selected = _run_highlight_analysis(video_path, rank)
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise ProductionRunError(str(exc)) from exc

    if len(selected) < rank:
        raise ProductionRunError(
            f"Job {job_id} only has {len(selected)} candidate(s) after overlap "
            f"suppression; rank {rank} is out of range."
        )
    candidate = selected[rank - 1]

    output_dir = settings.work_dir / "highlights"
    output_dir.mkdir(parents=True, exist_ok=True)

    reframed_path = output_dir / _reframed_filename(
        job_id, rank, candidate.start_seconds, candidate.end_seconds
    )
    captioned_path = output_dir / _captioned_filename(
        job_id, rank, candidate.start_seconds, candidate.end_seconds
    )

    if captioned_path.is_file():
        final_video_path = captioned_path
        has_captions = True
        caption_segment_count = None
    else:
        if not reframed_path.is_file():
            try:
                reframe_to_vertical(
                    video_path,
                    reframed_path,
                    candidate.start_seconds,
                    candidate.end_seconds,
                    horizontal_offset_ratio=horizontal_offset_ratio,
                )
            except VerticalReframeError as exc:
                raise ProductionRunError(str(exc)) from exc

        try:
            recognizer = FasterWhisperRecognizer(model_size=model_size)
            segments = recognizer.transcribe(reframed_path)
        except TranscriptionError as exc:
            raise ProductionRunError(str(exc)) from exc

        try:
            caption_result = burn_captions(reframed_path, captioned_path, segments)
            final_video_path = captioned_path
            has_captions = True
            caption_segment_count = caption_result.segment_count
        except CaptionError as exc:
            if _NO_SPEECH_MARKER in str(exc):
                final_video_path = reframed_path
                has_captions = False
                caption_segment_count = 0
            else:
                raise ProductionRunError(str(exc)) from exc

    quality_gate = run_quality_gate(final_video_path, quality_gate_config)

    package: PackageValidation | None = None
    if quality_gate.passed:
        dest_root = package_dest_root or _DEFAULT_PACKAGE_ROOT
        expected_package_dir = dest_root / final_video_path.stem
        if not expected_package_dir.is_dir():
            try:
                package_short(final_video_path, dest_root, config=quality_gate_config)
            except PackagingError as exc:
                raise ProductionRunError(str(exc)) from exc

        # Never blindly trust the directory (freshly created or found
        # already on disk from a prior run) - always re-validate via the
        # Phase 9 contract before it is considered usable.
        try:
            package = validate_package(
                expected_package_dir, quality_gate_config=quality_gate_config
            )
        except PublishingError as exc:
            raise ProductionRunError(
                f"Package at {expected_package_dir} failed validation, refusing to reuse or "
                f"report it as usable: {exc}"
            ) from exc

    return ProductionRunResult(
        job_id=job_id,
        rank=rank,
        source_title=job["source_title"],
        candidate_score=candidate.score,
        start_seconds=candidate.start_seconds,
        end_seconds=candidate.end_seconds,
        reframed_video_path=reframed_path,
        has_captions=has_captions,
        caption_segment_count=caption_segment_count,
        final_video_path=final_video_path,
        quality_gate=quality_gate,
        package=package,
    )


def run_production(
    job_id: int,
    rank: int,
    repository: JobRepository,
    settings: Settings,
    *,
    horizontal_offset_ratio: float = 0.5,
    model_size: str = "base",
    quality_gate_config: QualityGateConfig | None = None,
    package_dest_root: Path | None = None,
) -> ProductionRunResult:
    """Public manual-run entry point (used by the `production-run` CLI
    command). Enters repository.running() exactly once to look up and
    validate the job, then leaves the repository context before
    delegating all media processing to _run_production_loaded_job() -
    the database connection pool is never held open during highlight
    analysis, reframing, ASR, captioning, quality gating, or packaging.

    Never mutates JobRepository (read-only get_job() only, same as
    Phases 5-9), never touches YouTube, never uploads.
    """
    if rank < 1:
        raise ProductionRunError("rank must be >= 1.")

    job, video_path = _load_rights_confirmed_local_job(job_id, repository)

    return _run_production_loaded_job(
        job,
        video_path,
        rank,
        settings,
        horizontal_offset_ratio=horizontal_offset_ratio,
        model_size=model_size,
        quality_gate_config=quality_gate_config,
        package_dest_root=package_dest_root,
    )


# ---------------------------------------------------------------------------
# Local upload-state derivation (no DB schema change - filesystem only)
# ---------------------------------------------------------------------------


def local_upload_state(package_dir: Path) -> str:
    """Derive local publish state purely from the artifacts a validated
    package/publish run leaves behind - no DB schema change. Returns one
    of "published" (upload_receipt.json present - publishing already
    complete, NEVER upload again), "ambiguous" (upload_attempt.json
    present with no receipt - a prior attempt's outcome is unknown; the
    remote upload may have already succeeded even though this file was
    never confirmed - STOP, never retry automatically), or "none" (no
    marker present - eligible for a first attempt). Purely a read-only
    filesystem check; never creates or deletes either marker file."""
    if (package_dir / _UPLOAD_RECEIPT_FILENAME).is_file():
        return "published"
    if (package_dir / _UPLOAD_ATTEMPT_FILENAME).is_file():
        return "ambiguous"
    return "none"


# ---------------------------------------------------------------------------
# Automatic single-job selection + run ("production-run-once")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkippedCandidate:
    job_id: int
    reason: str


@dataclass(frozen=True)
class ProductionRunOnceResult:
    capture_scan: CaptureScanResult
    selected_job_id: int | None
    run: ProductionRunResult | None
    skipped: list[SkippedCandidate] = field(default_factory=list)


def _precheck_local_state(job_id: int, package_dest_root: Path) -> str:
    """Cheap, read-only precheck for job_id's rank-1 package - PURE
    FILESYSTEM: a glob for this job's deterministic rank-1 package
    directory name prefix plus marker-file existence checks. No video
    decode, no highlight analysis, no media processing of any kind (the
    package directory name embeds the candidate window's start/end
    timestamps, but production-run-once always uses rank 1 against an
    unchanged source, which is deterministic - the same candidate window
    every time - so a prior run's package, if any, is reliably found by
    job id prefix alone without needing to recompute the window here).
    Returns "published", "ambiguous", or "none"."""
    if not package_dest_root.is_dir():
        return "none"
    prefix = f"job-{job_id}-highlight-01-"
    package_dirs = [p for p in package_dest_root.glob(f"{prefix}*") if p.is_dir()]
    states = {local_upload_state(p) for p in package_dirs}
    if "published" in states:
        return "published"
    if "ambiguous" in states:
        return "ambiguous"
    return "none"


def run_production_once(
    repository: JobRepository,
    settings: Settings,
    *,
    capture_scan_directory: Path | None = None,
    horizontal_offset_ratio: float = 0.5,
    model_size: str = "base",
    quality_gate_config: QualityGateConfig | None = None,
    package_dest_root: Path | None = None,
) -> ProductionRunOnceResult:
    """The operational entry point: scan for new captures (idempotent,
    never auto-confirms rights - reuses capture_scan.scan_captures()
    unmodified), then deterministically select and process AT MOST ONE
    eligible local job.

    Eligibility mirrors the real queue-processing contract, not merely
    "rights confirmed": a candidate must have status == "pending",
    rights_confirmed == True, a local source_path, and no youtube_id
    already recorded. This deliberately excludes "uploaded", "rendered",
    "processing", "quarantined", and "failed" rows - a rights-confirmed
    job that was ever quarantined (including by an operator, or as a
    legacy pipeline side effect) or already carries a youtube_id must
    NOT be picked up automatically; it requires the existing explicit
    operator retry path (rights-approve / a manual requeue) to become
    "pending" again before this runner will ever touch it.

    Selection order is ascending job id (a stable, deterministic FIFO).
    For each eligible candidate in that order, ONLY a cheap, read-only,
    filesystem-only precheck (_precheck_local_state() - no video decode,
    no highlight analysis) is performed to detect a pre-existing
    receipt/attempt from an earlier run under the same job id; a
    candidate found "published" or "ambiguous" this way is skipped
    (recorded in `skipped`) WITHOUT any media processing, and the next
    candidate is tried.

    The moment a candidate clears that precheck, it is selected and
    _run_production_loaded_job() is called EXACTLY ONCE for the entire
    invocation, directly against the row already in hand from the single
    list_jobs() snapshot below (never a second database round-trip, and
    never through the public run_production() - the repository's
    connection pool is already closed by that point and psycopg_pool
    does not support reopening a closed pool). Whatever happens to that
    one job from that point on - a quality-gate failure, a package-
    validation failure, a genuine analysis/reframe/caption error (raised
    as ProductionRunError, propagated to the caller) - this invocation
    ends for that job. It never falls through to try a different
    candidate; "at most one job processed per invocation" is a hard
    guarantee, not merely a preference.

    If no candidate clears the precheck, selected_job_id is None (the
    CLI prints "NO ELIGIBLE JOB" and exits 0 - a normal empty-queue
    outcome, not a failure). Never mutates JobRepository beyond what
    scan_captures() itself already does (INSERT-only registration of new
    captures with rights_confirmed=False) - no job status/attempts/
    rights change, no legacy ContentEngine/claim_next semantics.

    Uses exactly ONE `with repository.running():` block, covering both
    scan_captures() and list_jobs() - the connection pool is opened once
    and closed once per invocation, never reopened. All subsequent
    candidate selection and (if any) media processing happens after that
    block has already exited, so long-running highlight analysis/
    reframe/ASR/captioning never holds a database connection open.
    """
    with repository.running():
        scan_result = scan_captures(
            capture_scan_directory or settings.capture_source_dir,
            repository,
            stability_wait_seconds=settings.capture_stability_wait_seconds,
        )
        all_jobs = repository.list_jobs()

    dest_root = package_dest_root or _DEFAULT_PACKAGE_ROOT

    candidates = sorted(
        (
            job
            for job in all_jobs
            if job.get("status") == "pending"
            and job.get("rights_confirmed")
            and job.get("source_path")
            and not job.get("youtube_id")
        ),
        key=lambda job: job["id"],
    )

    skipped: list[SkippedCandidate] = []
    selected_job: dict[str, Any] | None = None
    for job in candidates:
        job_id = job["id"]
        state = _precheck_local_state(job_id, dest_root)
        if state == "published":
            skipped.append(SkippedCandidate(job_id=job_id, reason="already published"))
            continue
        if state == "ambiguous":
            skipped.append(
                SkippedCandidate(
                    job_id=job_id,
                    reason="ambiguous upload state - operator reconciliation required",
                )
            )
            continue
        selected_job = job
        break

    if selected_job is None:
        return ProductionRunOnceResult(
            capture_scan=scan_result, selected_job_id=None, run=None, skipped=skipped
        )

    selected_job_id = selected_job["id"]
    video_path = _validate_job_and_source(selected_job)

    # The ONE and only media-processing call this invocation ever makes.
    # Any exception here (ProductionRunError) propagates to the caller
    # rather than being swallowed to try another candidate. Calls the
    # internal loaded-job helper directly - NOT the public
    # run_production() - since the repository context above has already
    # closed the connection pool.
    run_result = _run_production_loaded_job(
        selected_job,
        video_path,
        1,
        settings,
        horizontal_offset_ratio=horizontal_offset_ratio,
        model_size=model_size,
        quality_gate_config=quality_gate_config,
        package_dest_root=dest_root,
    )

    return ProductionRunOnceResult(
        capture_scan=scan_result,
        selected_job_id=selected_job_id,
        run=run_result,
        skipped=skipped,
    )


# ---------------------------------------------------------------------------
# Read-only status report ("production-status")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobProductionState:
    job_id: int
    source_title: str
    state: str


@dataclass(frozen=True)
class ProductionStatusReport:
    awaiting_rights: int
    rejected: int
    rights_approved_eligible: int
    processing: int
    packaged: int
    uploaded_private: int
    ambiguous: int
    jobs: list[JobProductionState]


def _classify_job_state(job: dict[str, Any], settings: Settings, package_dest_root: Path) -> str:
    """Pure filesystem read - no video decode, no highlight analysis, no
    network. Discovers any existing local artifacts for this job purely
    by globbing for its deterministic filename prefix
    ("job-{id}-highlight-"), so a full status report never has to re-run
    (comparatively expensive) highlight analysis for every job just to
    describe where it stands."""
    if not job.get("rights_confirmed"):
        # Mirrors JobRepository.list_pending_rights_review()'s own
        # reviewable-state predicate exactly, so this status report is
        # truthful about what the rights-review CLI would actually show:
        # a job that was never reviewed (status='pending') or was only
        # auto-quarantined before an operator could review it (the
        # AUTO_QUARANTINE_REASON marker) is genuinely still "awaiting
        # rights". An explicitly operator-rejected job (status=
        # 'quarantined' with a DIFFERENT last_error, e.g. "Rights
        # rejected by operator.") already had its rights decision made -
        # reporting it as "awaiting rights" would be false.
        status = job.get("status")
        last_error = job.get("last_error")
        auto_quarantined = status == "quarantined" and last_error == AUTO_QUARANTINE_REASON
        if status == "pending" or auto_quarantined:
            return "awaiting_rights"
        return "rejected"

    job_id = job["id"]
    prefix = f"job-{job_id}-highlight-"

    package_dirs = (
        sorted(package_dest_root.glob(f"{prefix}*")) if package_dest_root.is_dir() else []
    )
    for package_dir in package_dirs:
        if not package_dir.is_dir():
            continue
        if (package_dir / _UPLOAD_RECEIPT_FILENAME).is_file():
            return "uploaded_private"
    for package_dir in package_dirs:
        if package_dir.is_dir() and (package_dir / _UPLOAD_ATTEMPT_FILENAME).is_file():
            return "ambiguous"
    if any(p.is_dir() for p in package_dirs):
        return "packaged"

    highlights_dir = settings.work_dir / "highlights"
    if highlights_dir.is_dir() and any(highlights_dir.glob(f"{prefix}*")):
        return "processing"

    return "rights_approved_eligible"


def production_status(
    repository: JobRepository,
    settings: Settings,
    *,
    package_dest_root: Path | None = None,
) -> ProductionStatusReport:
    """Read-only status report across every job. No database write, no
    network I/O, no video decoding. See _classify_job_state() for the
    per-job classification rule."""
    dest_root = package_dest_root or _DEFAULT_PACKAGE_ROOT

    with repository.running():
        all_jobs = repository.list_jobs()

    counts = {
        "awaiting_rights": 0,
        "rejected": 0,
        "rights_approved_eligible": 0,
        "processing": 0,
        "packaged": 0,
        "uploaded_private": 0,
        "ambiguous": 0,
    }
    jobs: list[JobProductionState] = []
    for job in all_jobs:
        state = _classify_job_state(job, settings, dest_root)
        counts[state] += 1
        jobs.append(
            JobProductionState(job_id=job["id"], source_title=job["source_title"], state=state)
        )

    return ProductionStatusReport(
        awaiting_rights=counts["awaiting_rights"],
        rejected=counts["rejected"],
        rights_approved_eligible=counts["rights_approved_eligible"],
        processing=counts["processing"],
        packaged=counts["packaged"],
        uploaded_private=counts["uploaded_private"],
        ambiguous=counts["ambiguous"],
        jobs=jobs,
    )
