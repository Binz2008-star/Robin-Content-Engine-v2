from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .captioner import CaptionError, burn_captions
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
from .quality_gate import (
    PackageResult,
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


class ProductionRunError(Exception):
    """Raised for any Production Runner failure: missing/unconfirmed job,
    analysis failure, reframe failure, a genuine (non-no-speech)
    captioning failure, or a packaging failure. A clip with no detected
    speech is NOT an error - see run_production()'s caption-fallback
    handling."""


def _load_rights_confirmed_local_job(
    job_id: int, repository: JobRepository
) -> tuple[dict[str, Any], Path]:
    """Read-only job lookup, mirroring cli.py's own helper of the same
    name (used by highlight-scan/highlight-cut/highlight-reframe/
    highlight-caption) field-for-field. Duplicated here rather than
    imported from cli.py to avoid any risk of regressing those already-
    proven, already-shipped commands via a shared-code refactor - the
    tradeoff of a small amount of duplicated glue against touching code
    that has already carried a real production job through a real
    private YouTube upload. Never claims the job or mutates any state."""
    with repository.running():
        job = repository.get_job(job_id)

    if job is None:
        raise ProductionRunError(f"Job {job_id} not found.")
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
    package: PackageResult | None


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
    """Orchestrate one job/rank through every already-proven local stage -
    highlight analysis, 9:16 reframe, local ASR + caption burn-in, the
    Phase 8D quality gate, and Phase 8D packaging - reusing every
    underlying module unmodified. Does NOT publish; see publishing.py's
    dry_run()/execute_private_upload() for that, called separately by the
    CLI against this function's returned package directory.

    Resumable by construction: each expensive stage's existing
    deterministic filename and refuse-to-overwrite behavior is used to
    skip already-completed work on a re-run, rather than introducing a
    new state-file format. The one ambiguous case - a reframed file
    exists but no captioned file does, e.g. from an interrupted prior
    run - is resolved conservatively by always re-attempting captioning
    against the existing reframed file (idempotent - the same audio
    always transcribes to the same result) rather than guessing whether
    the prior run had already determined "no speech".

    A clip with no detected speech falls back to using the reframed
    (uncaptioned) clip as the final artifact rather than failing the
    whole run - this is the one new behavior beyond pure orchestration
    this module introduces. Every other failure (missing/unconfirmed
    job, analysis failure, reframe failure, a genuine transcription/
    caption-burn failure, or a quality-gate/packaging failure) raises
    ProductionRunError with an explicit reason.

    Never mutates JobRepository (read-only get_job() only, same as
    Phases 5-9), never touches YouTube, never uploads.
    """
    if rank < 1:
        raise ProductionRunError("rank must be >= 1.")

    job, video_path = _load_rights_confirmed_local_job(job_id, repository)

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

    package: PackageResult | None = None
    if quality_gate.passed:
        dest_root = package_dest_root or _DEFAULT_PACKAGE_ROOT
        expected_package_dir = dest_root / final_video_path.stem
        if expected_package_dir.is_dir():
            manifest_path = expected_package_dir / "manifest.json"
            packaged_video_path = expected_package_dir / final_video_path.name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            package = PackageResult(
                package_dir=expected_package_dir,
                packaged_video_path=packaged_video_path,
                manifest_path=manifest_path,
                manifest=manifest,
            )
        else:
            try:
                package = package_short(final_video_path, dest_root, config=quality_gate_config)
            except PackagingError as exc:
                raise ProductionRunError(str(exc)) from exc

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
