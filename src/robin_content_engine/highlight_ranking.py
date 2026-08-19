from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .ai_logic import (
    ContentGenerator,
    extract_game_name,
    validate_ranking_coverage,
    validate_ranking_hooks,
)
from .clip_selector import HighlightCandidate
from .config import Settings
from .transcription import TranscriptSegment

logger = logging.getLogger(__name__)

# Format version of the per-rank transcript files this module READS. The
# production pipeline's caption stage writes these files
# (work/transcripts/job-<id>-rank-<n>.json) in a later PR; this module only
# ever reads them, and any version mismatch is treated as "no transcript".
_TRANSCRIPT_FORMAT_VERSION = 1

# Format version of the ranking report this module WRITES to
# work/rankings/job-<id>.json.
_RANKING_FORMAT_VERSION = 1


class HighlightRankingError(Exception):
    pass


@dataclass(frozen=True)
class RankedHighlight:
    new_rank: int
    original_rank: int
    candidate: HighlightCandidate
    hook: str | None
    ai_reason: str | None


@dataclass(frozen=True)
class HighlightRankingResult:
    job_id: int
    source_title: str
    duration_seconds: float
    method: str
    ai_failure_reason: str | None
    candidates: list[RankedHighlight]


# ---------------------------------------------------------------------------
# Per-rank transcript loading (read-only; a later PR writes these files)
# ---------------------------------------------------------------------------


def transcript_file_for(job_id: int, rank: int, transcripts_dir: Path) -> Path:
    """Deterministic per-job-per-rank transcript path, mirroring the scheme
    the production pipeline's caption stage uses
    (work/transcripts/job-<id>-rank-<n>.json)."""
    return transcripts_dir / f"job-{job_id}-rank-{rank}.json"


def load_transcript(path: Path) -> list[TranscriptSegment] | None:
    """Read and validate a per-rank transcript file. Returns the transcript
    segments, or None on ANY problem (missing file, malformed JSON, wrong
    format version, invalid or empty entries) - a missing or unreadable
    transcript is treated as "no transcript available" for the ranking
    prompt, never as a command failure.

    Expected file format (written by a later PR):
    {"format_version": 1, "job_id": <id>, "rank": <n>,
     "segments": [{"start_seconds": 0.0, "end_seconds": 2.5, "text": "..."}]}
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("format_version") != _TRANSCRIPT_FORMAT_VERSION:
        return None
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return None
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            return None
        try:
            start_seconds = float(item["start_seconds"])
            end_seconds = float(item["end_seconds"])
            text = str(item["text"])
        except (KeyError, TypeError, ValueError):
            return None
        if end_seconds < start_seconds:
            return None
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            segments.append(
                TranscriptSegment(
                    start_seconds=start_seconds, end_seconds=end_seconds, text=cleaned
                )
            )
    if not segments:
        return None
    return segments


# ---------------------------------------------------------------------------
# Ranking prompt (deterministic context - the AI sees only signals + words)
# ---------------------------------------------------------------------------


def _render_transcript_text(segments: list[TranscriptSegment] | None) -> str:
    if not segments:
        return "(no transcript available)"
    joined = " ".join(segment.text for segment in segments if segment.text.strip())
    if not joined:
        return "(no transcript available)"
    return f'"{joined}"'


def build_ranking_context(
    source_title: str,
    candidates: Sequence[HighlightCandidate],
    transcripts: Sequence[list[TranscriptSegment] | None],
) -> str:
    """Deterministic context block handed to the ranking generator: the game
    (extracted from the source title), the ALREADY-selected candidate
    windows with their per-candidate deterministic signals, and any
    transcript text per candidate. Never invents content - the AI sees only
    real transcribed words and signal values, never the video itself."""
    game = extract_game_name(source_title)
    lines = [
        f"Game: {game}",
        f"Source title: {source_title}",
        "Original gameplay footage recorded by Robin for the Robin Life & Gaming channel. "
        "You cannot see the video itself - judge ONLY the signal scores below and any "
        "transcript text.",
        "",
        "Highlight candidates already selected (candidate numbers are their current, "
        "score-based order; your task is to REORDER them):",
    ]
    for index, candidate in enumerate(candidates):
        transcript_text = _render_transcript_text(
            transcripts[index] if index < len(transcripts) else None
        )
        lines.append(
            f"Candidate {index + 1}: {candidate.start_seconds:.1f}s-"
            f"{candidate.end_seconds:.1f}s ({candidate.duration_seconds:.1f}s) "
            f"score={candidate.score:.3f}"
        )
        lines.append(
            f"  audio={candidate.audio_score:.3f} motion={candidate.motion_score:.3f} "
            f"scene={candidate.scene_signal:.3f} - {candidate.reason}"
        )
        lines.append(f"  transcript: {transcript_text}")
    lines.append("")
    lines.append(
        'Return a JSON object: {"ranking": [{"candidate": <original candidate number>, '
        '"hook": "...", "reason": "..."}, ...]} ordered best-first.'
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core ranking orchestration
# ---------------------------------------------------------------------------


def rank_highlights(
    job_id: int,
    source_title: str,
    duration_seconds: float,
    candidates: Sequence[HighlightCandidate],
    settings: Settings,
    generator: ContentGenerator,
    *,
    transcripts_dir: Path,
) -> HighlightRankingResult:
    """AI-assisted re-ranking of a job's ALREADY-computed highlight
    candidates, using each candidate's deterministic signals plus its
    per-rank transcript (if one is stored). Purely advisory and read-only:
    never changes job status, rights_confirmed, or any database state - the
    only output is the returned result, which the CLI persists to
    work/rankings/job-<id>.json.

    Deterministic fallback on ANY AI failure (missing/unusable API key,
    network error, empty/malformed/partial-coverage response, safety
    rejection, exhausted retries): the candidates are returned in their
    original score order with no hooks, method='deterministic-fallback'.
    """
    if not candidates:
        raise HighlightRankingError("No candidates to rank.")

    method = "deterministic-fallback"
    failure_reason: str | None = None
    ranked: list[RankedHighlight] = []

    if settings.deepseek_api_key:
        transcripts = [
            load_transcript(transcript_file_for(job_id, index + 1, transcripts_dir))
            for index in range(len(candidates))
        ]
        context = build_ranking_context(source_title, candidates, transcripts)
        language = getattr(settings, "youtube_metadata_language", "arabic")
        try:
            ai_ranking = generator.rank_candidates(
                context, language, candidate_count=len(candidates)
            )
            # Defense in depth: re-validate the response here even though the
            # real ContentGenerator already does - a partial/duplicated/
            # out-of-range ordering or a banned hook must trigger the
            # deterministic fallback regardless of which generator produced it.
            validate_ranking_coverage(ai_ranking, len(candidates))
            validate_ranking_hooks(ai_ranking)
        except Exception as exc:
            logger.warning(
                "AI highlight ranking failed for job %s; falling back to score order.",
                job_id,
                exc_info=True,
            )
            failure_reason = str(exc)
        else:
            ranked = [
                RankedHighlight(
                    new_rank=new_rank,
                    original_rank=entry.candidate,
                    candidate=candidates[entry.candidate - 1],
                    hook=entry.hook,
                    ai_reason=entry.reason,
                )
                for new_rank, entry in enumerate(ai_ranking.ranking, start=1)
            ]
            method = "ai"
    else:
        failure_reason = "DeepSeek API key is not configured."

    if not ranked:
        ranked = [
            RankedHighlight(
                new_rank=index + 1,
                original_rank=index + 1,
                candidate=candidate,
                hook=None,
                ai_reason=None,
            )
            for index, candidate in enumerate(candidates)
        ]

    return HighlightRankingResult(
        job_id=job_id,
        source_title=source_title,
        duration_seconds=duration_seconds,
        method=method,
        ai_failure_reason=failure_reason,
        candidates=ranked,
    )


# ---------------------------------------------------------------------------
# Ranking report persistence (work/rankings/job-<id>.json)
# ---------------------------------------------------------------------------


def write_ranking_file(result: HighlightRankingResult, rankings_dir: Path) -> Path:
    """Persist the ranking report atomically (tmp + replace) to
    work/rankings/job-<id>.json so an interrupted write can never leave a
    partially-written report that would later look valid. A re-run replaces
    the previous report for the same job - the report is advisory output,
    not protected upload state. No secrets are ever written."""
    payload = {
        "format_version": _RANKING_FORMAT_VERSION,
        "job_id": result.job_id,
        "source_title": result.source_title,
        "duration_seconds": result.duration_seconds,
        "generated_at": datetime.now(UTC).isoformat(),
        "method": result.method,
        "ai_failure_reason": result.ai_failure_reason,
        "candidates": [
            {
                "new_rank": ranked.new_rank,
                "original_rank": ranked.original_rank,
                "start_seconds": ranked.candidate.start_seconds,
                "end_seconds": ranked.candidate.end_seconds,
                "duration_seconds": ranked.candidate.duration_seconds,
                "score": ranked.candidate.score,
                "audio_score": ranked.candidate.audio_score,
                "motion_score": ranked.candidate.motion_score,
                "scene_signal": ranked.candidate.scene_signal,
                "reason": ranked.candidate.reason,
                "hook": ranked.hook,
                "ai_reason": ranked.ai_reason,
            }
            for ranked in result.candidates
        ],
    }
    rankings_dir.mkdir(parents=True, exist_ok=True)
    out_path = rankings_dir / f"job-{result.job_id}.json"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path
