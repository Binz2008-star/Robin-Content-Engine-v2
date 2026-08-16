from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    TimeWindow,
    compute_scene_density,
    extract_audio_activity,
    extract_motion_activity,
    generate_time_windows,
)
from .highlight_scoring import score_windows
from .publishing import (
    _UPLOAD_STATE_FORMAT_VERSION,
    PackageValidation,
    PublishingError,
    _write_json_atomic,
    validate_package,
)
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
# publishing.py's own _ATTEMPT_FILENAME/_RECEIPT_FILENAME
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
    fallback handling.

    `retryable` distinguishes failures whose outcome could differ on a
    retry (transient I/O, ffmpeg, ASR, network) from failures that are
    deterministic - the same job and source would fail identically every
    time (missing source file, analysis failure, out-of-range rank, a
    package that fails validation after a fresh rebuild). The automatic
    runner (run_production_once) quarantines deterministic failures so
    the queue is never blocked forever on a job that cannot succeed;
    retryable failures still propagate to the caller (the scheduled
    task's logs) and are retried on the next invocation.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


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
    # Duplicate-upload guard, enforced server-side on BOTH entry points
    # (manual run_production and the automatic runner): a job that was
    # already uploaded - the DB row says so - must never be processed or
    # re-uploaded, regardless of what local files happen to exist.
    # run_production_once()'s candidate filter already excludes such rows,
    # so this is the authoritative backstop for the manual path and for
    # any future caller. Deterministic: the row will not become
    # "uploaded" again on its own, so a retry could never succeed.
    if job.get("youtube_id") or job.get("status") == "uploaded":
        raise ProductionRunError(
            f"Job {job_id} has already been uploaded (status={job.get('status')!r}, "
            f"youtube_id={job.get('youtube_id')!r}) - refusing to process or re-upload it.",
            retryable=False,
        )
    source_path = job.get("source_path")
    if not source_path:
        raise ProductionRunError(
            f"Job {job_id} has no local source_path to analyze "
            "(remote sources are not supported).",
            retryable=False,
        )
    video_path = Path(source_path)
    if not video_path.is_file():
        raise ProductionRunError(
            f"Source file does not exist: {video_path}",
            retryable=False,
        )
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
    real production job through a real YouTube upload. Never
    claims the job or mutates any state."""
    with repository.running():
        job = repository.get_job(job_id)

    if job is None:
        raise ProductionRunError(f"Job {job_id} not found.")
    video_path = _validate_job_and_source(job)
    return job, video_path


def _run_highlight_analysis(
    video_path: Path,
    top_n: int,
    *,
    analysis_cache_path: Path | None = None,
) -> tuple[list[SceneBoundary], list[HighlightCandidate]]:
    """Mirrors cli.py's own helper of the same name field-for-field - see
    that docstring for the full rationale (deterministic scoring,
    suppress_overlaps() prefix-stability across top_n, read-only/no-DB-
    write). Duplicated for the same reason as
    _load_rights_confirmed_local_job above.

    `analysis_cache_path`, when given (the automatic runner passes one),
    persists the expensive analysis results (scene detection plus the
    raw audio/motion/scene signals) keyed by the source file's identity
    (path + size + mtime) and a format version. On a resume/re-run of the
    same unchanged source the expensive stages are skipped entirely and
    the cached signals flow through the SAME deterministic scoring and
    selection code, so the selected candidate windows are identical to a
    fresh analysis. The cache is a pure performance optimization: any
    mismatch, malformation, or version change is treated as a miss and
    everything is recomputed - correctness never depends on the cache.
    """
    source_identity = _source_identity(video_path)
    if analysis_cache_path is not None:
        cached = _load_analysis_cache(analysis_cache_path, source_identity)
        if cached is not None:
            scenes, raw_rms, raw_flux, raw_motion, raw_scene = cached
            windows = generate_time_windows(scenes[-1].end_seconds, _HIGHLIGHT_WINDOW_SECONDS)
            return scenes, _select_candidates(
                windows, raw_rms, raw_flux, raw_motion, raw_scene, top_n
            )

    scenes = detect_scenes(video_path)
    duration_seconds = scenes[-1].end_seconds

    windows = generate_time_windows(duration_seconds, _HIGHLIGHT_WINDOW_SECONDS)
    raw_rms, raw_flux = extract_audio_activity(video_path, windows)
    raw_motion = extract_motion_activity(video_path, windows)
    raw_scene = compute_scene_density(scenes, windows)

    selected = _select_candidates(windows, raw_rms, raw_flux, raw_motion, raw_scene, top_n)

    if analysis_cache_path is not None:
        _store_analysis_cache(
            analysis_cache_path,
            source_identity,
            scenes,
            raw_rms,
            raw_flux,
            raw_motion,
            raw_scene,
        )
    return scenes, selected


def _select_candidates(
    windows: Sequence[TimeWindow],
    raw_rms: Sequence[float],
    raw_flux: Sequence[float],
    raw_motion: Sequence[float],
    raw_scene: Sequence[float],
    top_n: int,
) -> list[HighlightCandidate]:
    """The scoring + overlap-suppression tail of a highlight analysis -
    pure and deterministic, shared by the fresh-analysis and cached-
    analysis paths so both produce byte-identical selections."""
    window_scores = score_windows(windows, raw_rms, raw_flux, raw_motion, raw_scene)

    selector_config = WindowSelectorConfig()
    ranked_candidates = generate_candidate_windows(window_scores, selector_config)
    return suppress_overlaps(
        ranked_candidates,
        iou_threshold=selector_config.overlap_iou_threshold,
        containment_threshold=selector_config.containment_threshold,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# Highlight-analysis cache (resumability of the expensive stages)
# ---------------------------------------------------------------------------

_ANALYSIS_CACHE_FORMAT_VERSION = 1


def _source_identity(video_path: Path) -> dict[str, Any]:
    stat = video_path.stat()
    return {
        "path": str(video_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _scene_to_list(scene: SceneBoundary) -> list[float]:
    return [
        scene.start_seconds,
        scene.end_seconds,
        float(scene.start_frame),
        float(scene.end_frame),
    ]


def _scene_from_list(raw: Any) -> SceneBoundary | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        return SceneBoundary(
            start_seconds=float(raw[0]),
            end_seconds=float(raw[1]),
            start_frame=int(raw[2]),
            end_frame=int(raw[3]),
        )
    except (TypeError, ValueError):
        return None


def _load_analysis_cache(
    cache_path: Path, source_identity: dict[str, Any]
) -> tuple[list[SceneBoundary], list[float], list[float], list[float], list[float]] | None:
    """Read and fully validate the analysis cache. Returns None on ANY
    problem (missing file, bad JSON, wrong format version, source
    identity mismatch, malformed entries, inconsistent signal lengths) -
    the caller then simply recomputes everything."""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("format_version") != _ANALYSIS_CACHE_FORMAT_VERSION:
        return None
    if payload.get("source") != source_identity:
        return None

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        return None
    scenes = [_scene_from_list(item) for item in raw_scenes]
    if any(scene is None for scene in scenes):
        return None
    scenes_typed = [scene for scene in scenes if scene is not None]

    signals: list[list[float]] = []
    for key in ("raw_rms", "raw_flux", "raw_motion", "raw_scene"):
        raw = payload.get(key)
        if not isinstance(raw, list):
            return None
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError):
            return None
        signals.append(values)

    windows = generate_time_windows(scenes_typed[-1].end_seconds, _HIGHLIGHT_WINDOW_SECONDS)
    if any(len(values) != len(windows) for values in signals):
        return None

    return (
        scenes_typed,
        signals[0],
        signals[1],
        signals[2],
        signals[3],
    )


def _store_analysis_cache(
    cache_path: Path,
    source_identity: dict[str, Any],
    scenes: list[SceneBoundary],
    raw_rms: list[float],
    raw_flux: list[float],
    raw_motion: list[float],
    raw_scene: list[float],
) -> None:
    """Persist the expensive analysis results atomically (tmp + replace)
    so an interrupted write can never leave a partially-written cache
    that would later look valid."""
    payload = {
        "format_version": _ANALYSIS_CACHE_FORMAT_VERSION,
        "source": source_identity,
        "scenes": [_scene_to_list(scene) for scene in scenes],
        "raw_rms": raw_rms,
        "raw_flux": raw_flux,
        "raw_motion": raw_motion,
        "raw_scene": raw_scene,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(cache_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(cache_path)


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


def _artifact_is_valid(path: Path, quality_gate_config: QualityGateConfig | None) -> bool:
    """Reuse decision for an existing reframed/captioned artifact: it must
    pass the SAME quality gate the final artifact is held to. A zero-byte,
    partial, stale, or corrupt artifact fails and is never reused - the
    caller deletes and rebuilds it. Pure read - never modifies anything."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    return run_quality_gate(path, quality_gate_config).passed


def _caption_segment_count_sidecar(captioned_path: Path) -> Path:
    """Sidecar recording how many caption segments the run that produced
    the captioned artifact burned in, so a resume can report a truthful
    count instead of None. Named after the captioned file itself, so it
    is rebuilt whenever the captioned file is."""
    return captioned_path.with_suffix(".segments.json")


def _read_caption_segment_count(captioned_path: Path) -> int | None:
    """Restore the caption segment count recorded by the run that produced
    the captioned artifact. Returns None (honest "unknown") if no sidecar
    exists or it is malformed - never guessed from anything else."""
    sidecar = _caption_segment_count_sidecar(captioned_path)
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    count = payload.get("segment_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    return count


def _write_caption_segment_count(captioned_path: Path, segment_count: int) -> None:
    """Durably record the caption segment count for the captioned
    artifact, written atomically alongside it."""
    sidecar = _caption_segment_count_sidecar(captioned_path)
    tmp_path = sidecar.with_name(sidecar.name + ".tmp")
    tmp_path.write_text(json.dumps({"segment_count": segment_count}), encoding="utf-8")
    tmp_path.replace(sidecar)


# ---------------------------------------------------------------------------
# Deterministic automatic metadata - no LLM, no TTS, no operator input
# ---------------------------------------------------------------------------

# YouTube's real title limit; the automatic metadata must never exceed it
# (publishing.build_publish_metadata() enforces the same bound at
# publish time - truncating here keeps the automatic path deterministic
# and publishable instead of failing at the last step).
_TITLE_MAX_LENGTH = 100
_TITLE_SUFFIX = " — Highlight"
_TITLE_ELLIPSIS = "..."


def build_automatic_metadata(source_title: str) -> tuple[str, str]:
    """Fixed, deterministic, truthful metadata for production-run-once.
    Never an LLM call, never TTS, never requires operator input for
    normal automatic operation. Long source titles are truncated so the
    resulting title always fits YouTube's 100-character limit while
    keeping the truthful " — Highlight" suffix; the ellipsis marks the
    truncation, and the result is deterministic for the same input."""
    title = f"{source_title}{_TITLE_SUFFIX}"
    if len(title) > _TITLE_MAX_LENGTH:
        prefix_budget = _TITLE_MAX_LENGTH - len(_TITLE_SUFFIX) - len(_TITLE_ELLIPSIS)
        title = f"{source_title[:prefix_budget].rstrip()}{_TITLE_ELLIPSIS}{_TITLE_SUFFIX}"
    description = "Automatically processed from operator-owned gameplay by Robin Content Engine."
    return title, description


def build_production_metadata(
    source_title: str, settings: Settings
) -> tuple[str, str, list[str]]:
    """Metadata for a production-run-once upload.

    When settings.youtube_ai_metadata is enabled (and a DeepSeek API key is
    configured), generates natural Gulf-Arabic title/description/tags via
    ContentGenerator using the same improved prompt as the rest of the
    pipeline. Any AI failure falls back to the deterministic English
    metadata so the scheduled task can never be blocked by the LLM being
    unavailable. Returns (title, description, tags)."""
    if getattr(settings, "youtube_ai_metadata", False) and settings.deepseek_api_key:
        try:
            from .ai_logic import ContentGenerator, build_ai_context

            generator = ContentGenerator(
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
            )
            generated = generator.generate(build_ai_context(source_title))
            return generated.title, generated.description, list(generated.tags)
        except Exception:
            logging.getLogger(__name__).warning(
                "AI metadata generation failed for %r; falling back to deterministic metadata.",
                source_title,
                exc_info=True,
            )
    title, description = build_automatic_metadata(source_title)
    return title, description, []


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
    analysis_cache_path: Path | None = None,
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
    new state-file format - BUT an existing artifact is only reused after
    it passes the same quality gate the final artifact is held to
    (_artifact_is_valid): a zero-byte, partial, stale, or corrupt
    reframed/captioned file is deleted and rebuilt, never silently
    reused. A resumed captioned artifact reports its caption segment
    count from a durable sidecar written when it was produced (None, an
    honest "unknown", if no sidecar exists). The one ambiguous case - a
    reframed file exists but no captioned file does, e.g. from an
    interrupted prior run - is resolved conservatively by always re-
    attempting captioning against the existing reframed file (idempotent
    - the same audio always transcribes to the same result) rather than
    guessing whether the prior run had already determined "no speech".

    An existing package directory is NEVER blindly trusted: whether
    freshly packaged this call or found already on disk from a prior
    run, it is always validated via publishing.validate_package() (the
    same Phase 9 contract youtube-publish-package itself uses) before
    being returned - manifest well-formed, quality_gate_passed=true as
    recorded, byte size/SHA-256 matching, and the quality gate re-run
    fresh. A corrupt or stale existing package that carries no upload
    marker is REBUILT from the fresh artifact rather than reused; a
    package carrying an upload attempt/receipt marker that fails
    validation is refused outright (protected upload state - see
    local_upload_state()).

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
        _scenes, selected = _run_highlight_analysis(
            video_path, rank, analysis_cache_path=analysis_cache_path
        )
    except (SceneDetectionError, FeatureExtractionError, ClipSelectionError) as exc:
        raise ProductionRunError(str(exc), retryable=False) from exc

    if len(selected) < rank:
        # Deterministic: the same (possibly cached) analysis selects the
        # same candidates every time, so this rank will never be in range
        # on a retry either.
        raise ProductionRunError(
            f"Job {job_id} only has {len(selected)} candidate(s) after overlap "
            f"suppression; rank {rank} is out of range.",
            retryable=False,
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
        if _artifact_is_valid(captioned_path, quality_gate_config):
            final_video_path = captioned_path
            has_captions = True
            caption_segment_count = _read_caption_segment_count(captioned_path)
        else:
            # A stale, partial, or corrupt captioned artifact is never
            # reused - delete it and rebuild from the reframed clip below.
            captioned_path.unlink(missing_ok=True)

    if not captioned_path.is_file():
        if reframed_path.is_file() and not _artifact_is_valid(
            reframed_path, quality_gate_config
        ):
            reframed_path.unlink(missing_ok=True)
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
            _write_caption_segment_count(captioned_path, caption_result.segment_count)
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
        if expected_package_dir.is_dir():
            try:
                existing_package = validate_package(
                    expected_package_dir, quality_gate_config=quality_gate_config
                )
            except PublishingError as exc:
                # An existing package directory is NEVER blindly trusted:
                # validate it first, and on failure REBUILD it from the
                # fresh artifact rather than reusing or reporting it.
                # Rebuilding is only safe when no upload has ever been
                # attempted for this package - if an upload attempt or
                # receipt marker exists, that local state is protected
                # (a rebuild could orphan it or misrepresent it) and
                # rebuilding is refused outright.
                upload_state = local_upload_state(expected_package_dir)
                if upload_state != "none":
                    raise ProductionRunError(
                        f"Package at {expected_package_dir} failed validation and carries an "
                        f"upload marker (local state {upload_state!r}) - refusing to rebuild "
                        f"or reuse it: {exc}",
                        retryable=False,
                    ) from exc
                shutil.rmtree(expected_package_dir)
            else:
                package = existing_package

        if package is None:
            if not expected_package_dir.is_dir():
                try:
                    package_short(final_video_path, dest_root, config=quality_gate_config)
                except PackagingError as exc:
                    raise ProductionRunError(str(exc)) from exc

            # Never blindly trust the directory (freshly created or found
            # already on disk from a prior run) - always re-validate via
            # the Phase 9 contract before it is considered usable. A
            # failure HERE is deterministic: the package was (re)built
            # from this exact artifact in this very call and still fails
            # validation, so no retry could ever succeed.
            try:
                package = validate_package(
                    expected_package_dir, quality_gate_config=quality_gate_config
                )
            except PublishingError as exc:
                raise ProductionRunError(
                    f"Package at {expected_package_dir} failed validation, refusing to reuse "
                    f"or report it as usable: {exc}",
                    retryable=False,
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
# Ambiguous-upload-state reconciliation ("production-reconcile")
# ---------------------------------------------------------------------------

# How far (in seconds) a matched upload's published_at may differ from the
# attempt marker's started_at and still count as the SAME upload. YouTube
# timestamps are second-precision; 15 minutes is generous for clock skew
# while still being far narrower than the gap between distinct uploads.
_RECONCILE_TIME_TOLERANCE_SECONDS = 900


@dataclass(frozen=True)
class ReconciliationOutcome:
    package_dir: Path
    resolved: bool
    match_count: int
    detail: str


def find_ambiguous_packages(*, package_dest_root: Path | None = None) -> list[Path]:
    """Filesystem-only discovery of every package in the "ambiguous"
    upload state (an upload_attempt.json marker without a receipt) under
    the package root. Pure reads - no network, no YouTube, no writes -
    so a caller can decide whether any YouTube access is needed at
    all."""
    dest_root = package_dest_root or _DEFAULT_PACKAGE_ROOT
    if not dest_root.is_dir():
        return []
    return sorted(
        p
        for p in dest_root.iterdir()
        if p.is_dir() and local_upload_state(p) == "ambiguous"
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def reconcile_ambiguous_uploads(
    sync: Any,
    *,
    package_dest_root: Path | None = None,
) -> list[ReconciliationOutcome]:
    """Resolve packages stuck in the "ambiguous" upload state: the local
    upload_attempt.json marker says an upload MAY have started, but no
    upload_receipt.json ever confirmed it, so the remote outcome is
    unknown and the pipeline refuses to retry automatically.

    This command settles the ambiguity by asking YouTube itself: it
    fetches the authenticated channel's current upload inventory (the
    same read-only fetch youtube-sync uses) and looks for a PRIVATE
    video whose published_at matches the attempt marker's started_at
    (within a 15-minute tolerance - a few seconds of YouTube timestamp
    granularity plus clock skew). Only when EXACTLY ONE candidate
    matches is the outcome unambiguous: the receipt is then written from
    the marker + the matched video's data (the same atomic write
    execute_private_upload() uses, with the marker's recorded
    package_sha256) and the attempt marker is removed, so the package
    transitions "ambiguous" -> "published" exactly as a confirmed
    upload would.

    Zero or multiple candidates mean the ambiguity is NOT resolvable
    from the inventory alone (the upload may never have happened, or
    several uploads were made in the window) - nothing is written, the
    marker is preserved, and the operator must look at YouTube
    manually. The command never guesses.

    Never mutates the database, never uploads, never deletes anything
    remotely - the only writes are the receipt/attempt-marker pair on
    an exactly-one-match resolution.
    """
    outcomes: list[ReconciliationOutcome] = []
    ambiguous_dirs = find_ambiguous_packages(package_dest_root=package_dest_root)
    if not ambiguous_dirs:
        return []

    snapshot = sync.fetch_snapshot()
    videos = snapshot.videos

    for package_dir in ambiguous_dirs:
        attempt_path = package_dir / _UPLOAD_ATTEMPT_FILENAME
        try:
            marker = json.loads(attempt_path.read_text(encoding="utf-8"))
            started_at = _as_utc(datetime.fromisoformat(marker["started_at"]))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            outcomes.append(
                ReconciliationOutcome(
                    package_dir=package_dir,
                    resolved=False,
                    match_count=0,
                    detail="attempt marker is unreadable/malformed - operator review required",
                )
            )
            continue

        tolerance = timedelta(seconds=_RECONCILE_TIME_TOLERANCE_SECONDS)
        matches = [
            video
            for video in videos
            if video.privacy_status == "private"
            and video.published_at is not None
            and abs(_as_utc(video.published_at) - started_at) <= tolerance
        ]

        if len(matches) == 1:
            matched = matches[0]
            receipt = {
                "format_version": marker.get("format_version", _UPLOAD_STATE_FORMAT_VERSION),
                "package_sha256": marker.get("package_sha256"),
                "youtube_video_id": matched.video_id,
                "channel_id": marker.get("authenticated_channel_id"),
                "privacy_status": "private",
                "uploaded_at": matched.published_at.isoformat(),
            }
            _write_json_atomic(package_dir / _UPLOAD_RECEIPT_FILENAME, receipt)
            attempt_path.unlink(missing_ok=True)
            outcomes.append(
                ReconciliationOutcome(
                    package_dir=package_dir,
                    resolved=True,
                    match_count=1,
                    detail=f"matched private video {matched.video_id} published "
                    f"{matched.published_at.isoformat()}",
                )
            )
        else:
            outcomes.append(
                ReconciliationOutcome(
                    package_dir=package_dir,
                    resolved=False,
                    match_count=len(matches),
                    detail=(
                        f"found {len(matches)} candidate private upload(s) in the "
                        "matching time window - not resolvable automatically, "
                        "operator review required"
                    ),
                )
            )

    return outcomes


# ---------------------------------------------------------------------------
# Automatic single-job selection + run ("production-run-once")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkippedCandidate:
    job_id: int
    reason: str


@dataclass(frozen=True)
class TerminalFailure:
    """A selected job that failed DETERMINISTICALLY - the same job and
    source would fail identically on any retry. run_production_once()
    quarantines such jobs (via JobRepository.mark_deterministic_failure,
    using its own fresh connection pool since the lookup pool is already
    closed) so the queue is never blocked on them again, and reports the
    outcome here for the CLI to print and exit non-zero."""

    job_id: int
    reason: str


@dataclass(frozen=True)
class ProductionRunOnceResult:
    capture_scan: CaptureScanResult
    selected_job_id: int | None
    run: ProductionRunResult | None
    skipped: list[SkippedCandidate] = field(default_factory=list)
    terminal_failure: TerminalFailure | None = None


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
    validation failure, a genuine analysis/reframe/caption error - this
    invocation ends for that job. It never falls through to try a
    different candidate; "at most one job processed per invocation" is a
    hard guarantee, not merely a preference.

    Failures are classified by whether a retry could possibly succeed:
    a RETRYABLE failure (transient I/O, ffmpeg, ASR, packaging, a
    package-validation failure on a PRE-EXISTING package that can
    legitimately be rebuilt next time) propagates as ProductionRunError
    to the caller for the scheduled task's logs, and the job is
    retried on the next invocation. A DETERMINISTIC failure - the same
    job and source would fail identically every time: a missing source
    file, an analysis failure, an out-of-range rank, a package that
    still fails validation after being freshly rebuilt this call, or a
    quality-gate failure on the produced artifact - is quarantined via
    JobRepository.mark_deterministic_failure() (which uses its own
    short-lived connection pool, since the lookup pool is already
    closed) with the failure reason recorded as last_error, and
    reported as a TerminalFailure in the result so the CLI can print it
    and exit non-zero. The queue is never blocked forever on a job that
    cannot succeed; the operator's existing explicit retry path
    (rights-approve / retry / a manual requeue) can still restore such
    a job to "pending" deliberately.

    If no candidate clears the precheck, selected_job_id is None (the
    CLI prints "NO ELIGIBLE JOB" and exits 0 - a normal empty-queue
    outcome, not a failure). Beyond scan_captures()'s own INSERT-only
    registration of new captures (rights_confirmed=False), the only
    JobRepository mutation is the deterministic-failure quarantine
    described above - never on the success path, and never a
    status/attempts/rights change for a job that was merely skipped or
    that ran to completion.

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

    def quarantine_terminal_failure(reason: str) -> ProductionRunOnceResult:
        """Quarantine the selected job as a deterministic (never-
        retryable) failure and build the invocation result carrying the
        TerminalFailure for the CLI to report. Uses
        mark_deterministic_failure() - a write that spins up its own
        short-lived pool, because this repository's lookup pool is
        already closed and psycopg_pool does not support reopening it."""
        repository.mark_deterministic_failure(selected_job_id, reason)
        return ProductionRunOnceResult(
            capture_scan=scan_result,
            selected_job_id=selected_job_id,
            run=None,
            skipped=skipped,
            terminal_failure=TerminalFailure(job_id=selected_job_id, reason=reason),
        )

    try:
        video_path = _validate_job_and_source(selected_job)
    except ProductionRunError as exc:
        if exc.retryable:
            raise
        return quarantine_terminal_failure(str(exc))

    # The ONE and only media-processing call this invocation ever makes.
    # A retryable exception here (ProductionRunError) propagates to the
    # caller rather than being swallowed to try another candidate. A
    # deterministic failure (exc.retryable is False) quarantines the job
    # and ends the invocation. Calls the internal loaded-job helper
    # directly - NOT the public run_production() - since the repository
    # context above has already closed the connection pool.
    analysis_cache_path = settings.work_dir / "analysis" / f"job-{selected_job_id}-analysis.json"
    try:
        run_result = _run_production_loaded_job(
            selected_job,
            video_path,
            1,
            settings,
            horizontal_offset_ratio=horizontal_offset_ratio,
            model_size=model_size,
            quality_gate_config=quality_gate_config,
            package_dest_root=dest_root,
            analysis_cache_path=analysis_cache_path,
        )
    except ProductionRunError as exc:
        if exc.retryable:
            raise
        return quarantine_terminal_failure(str(exc))

    if not run_result.quality_gate.passed:
        # A quality-gate failure on the produced artifact is a
        # deterministic outcome - the same source and analysis produce
        # the same artifact, which fails the same gate every time.
        # Quarantine it so the queue is not blocked by a job that can
        # never pass, and report the outcome to the caller (the run
        # result is still carried for the CLI to echo the gate details).
        reason = (
            "Quality gate failed on the produced artifact; the outcome is deterministic "
            "for this job and source."
        )
        repository.mark_deterministic_failure(selected_job_id, reason)
        return ProductionRunOnceResult(
            capture_scan=scan_result,
            selected_job_id=selected_job_id,
            run=run_result,
            skipped=skipped,
            terminal_failure=TerminalFailure(job_id=selected_job_id, reason=reason),
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
    inactive: int
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

    # File-based markers above (receipt/attempt/package/highlight) take
    # precedence: a receipt-bearing job stays "uploaded_private"
    # regardless of status. Only jobs that have genuinely finished
    # uploading - the DB row says status == "uploaded" - are reported as
    # uploaded_private (a "processing"/"rendered" row without a receipt
    # has not uploaded, whatever its status says).
    status = job.get("status")
    if status == "uploaded":
        return "uploaded_private"

    # Mirror run_production_once()'s own eligibility contract (status ==
    # "pending" AND rights_confirmed AND a local source_path AND no
    # youtube_id) instead of reporting it as eligible: a rights-confirmed
    # job in any other status (processing, rendered, failed, quarantined)
    # would never be auto-selected, so reporting it as eligible would be
    # false. Those jobs are "inactive" - rights are settled but the row
    # is not in a state the automatic runner will ever pick up (it
    # requires the operator's existing explicit retry path). This is
    # deliberately distinct from "rejected", which means the operator
    # explicitly rejected the rights on an UNCONFIRMED job.
    if status == "pending" and job.get("source_path") and not job.get("youtube_id"):
        return "rights_approved_eligible"
    return "inactive"


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
        "inactive": 0,
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
        inactive=counts["inactive"],
        jobs=jobs,
    )
