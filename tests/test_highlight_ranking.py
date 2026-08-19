from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.ai_logic import ContentGenerationError  # noqa: E402
from robin_content_engine.clip_selector import HighlightCandidate  # noqa: E402
from robin_content_engine.highlight_ranking import (  # noqa: E402
    HighlightRankingError,
    build_ranking_context,
    load_transcript,
    rank_highlights,
    transcript_file_for,
    write_ranking_file,
)
from robin_content_engine.models import CandidateRankingResult, RankedCandidateResult  # noqa: E402
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402


class FakeSettings:
    def __init__(
        self,
        *,
        deepseek_api_key: str = "sk-fake",
        youtube_metadata_language: str = "arabic",
    ) -> None:
        self.deepseek_api_key = deepseek_api_key
        self.youtube_metadata_language = youtube_metadata_language


class FakeGenerator:
    def __init__(self, response: CandidateRankingResult | None = None) -> None:
        self.response = response
        self.calls: list[tuple[str, str, int]] = []

    def rank_candidates(
        self, context: str, language: str, *, candidate_count: int
    ) -> CandidateRankingResult:
        self.calls.append((context, language, candidate_count))
        if self.response is None:
            raise ContentGenerationError("simulated AI failure")
        return self.response


def _candidate(
    start: float,
    end: float,
    *,
    score: float,
    audio: float,
    motion: float,
    scene: float,
    reason: str,
) -> HighlightCandidate:
    return HighlightCandidate(
        start_seconds=start,
        end_seconds=end,
        score=score,
        audio_score=audio,
        motion_score=motion,
        scene_signal=scene,
        reason=reason,
    )


def _ranking(*entries: tuple[int, str, str]) -> CandidateRankingResult:
    return CandidateRankingResult(
        ranking=[
            RankedCandidateResult(candidate=candidate_id, hook=hook, reason=reason)
            for candidate_id, hook, reason in entries
        ]
    )


def _two_candidates() -> list[HighlightCandidate]:
    return [
        _candidate(10.0, 40.0, score=0.8, audio=0.7, motion=0.6, scene=0.3, reason="audio spike"),
        _candidate(50.0, 80.0, score=0.9, audio=0.4, motion=0.9, scene=0.4, reason="high motion"),
    ]


# ---------------------------------------------------------------------------
# Transcript loading
# ---------------------------------------------------------------------------


def test_transcript_file_for_naming() -> None:
    path = transcript_file_for(34, 2, Path("work/transcripts"))
    assert path == Path("work/transcripts") / "job-34-rank-2.json"


def test_load_transcript_happy_path(tmp_path: Path) -> None:
    path = tmp_path / "job-7-rank-1.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "job_id": 7,
                "rank": 1,
                "segments": [
                    {"start_seconds": 0.0, "end_seconds": 2.5, "text": "  let's go  "},
                    {"start_seconds": 2.5, "end_seconds": 5.0, "text": "nice shot"},
                ],
            }
        ),
        encoding="utf-8",
    )

    segments = load_transcript(path)

    assert segments is not None
    assert segments == [
        TranscriptSegment(start_seconds=0.0, end_seconds=2.5, text="let's go"),
        TranscriptSegment(start_seconds=2.5, end_seconds=5.0, text="nice shot"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        {"format_version": 2, "segments": []},
        {"format_version": 1, "segments": "nope"},
        {"format_version": 1, "segments": [{"text": "missing timestamps"}]},
        {
            "format_version": 1,
            "segments": [{"start_seconds": 5.0, "end_seconds": 1.0, "text": "bad"}],
        },
        {
            "format_version": 1,
            "segments": [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "  "}],
        },
        "not a dict",
    ],
)
def test_load_transcript_malformed_returns_none(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "job-7-rank-1.json"
    if isinstance(payload, str) and payload.startswith("{"):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_transcript(path) is None


def test_load_transcript_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_transcript(tmp_path / "does-not-exist.json") is None


# ---------------------------------------------------------------------------
# Ranking context
# ---------------------------------------------------------------------------


def test_build_ranking_context_includes_signals_and_transcript() -> None:
    candidates = _two_candidates()
    transcripts: list[list[TranscriptSegment] | None] = [
        [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there")],
        None,
    ]

    context = build_ranking_context("Fortnite 2026-08-07 23-14-11", candidates, transcripts)

    assert "Game: Fortnite" in context
    assert "Candidate 1: 10.0s-40.0s (30.0s) score=0.800" in context
    assert "audio=0.700 motion=0.600 scene=0.300 - audio spike" in context
    assert '"hello there"' in context
    assert "Candidate 2: 50.0s-80.0s (30.0s) score=0.900" in context
    assert "(no transcript available)" in context
    assert "REORDER" in context


# ---------------------------------------------------------------------------
# rank_highlights
# ---------------------------------------------------------------------------


def test_rank_highlights_happy_path_reorders_with_hooks(tmp_path: Path) -> None:
    candidates = _two_candidates()
    generator = FakeGenerator(
        response=_ranking(
            (2, "best moment", "strong motion spike"),
            (1, "solid audio", "loud action"),
        )
    )

    result = rank_highlights(
        7,
        "Fortnite 2026-08-07 23-14-11",
        100.0,
        candidates,
        FakeSettings(),
        generator,
        transcripts_dir=tmp_path,
    )

    assert result.method == "ai"
    assert result.ai_failure_reason is None
    assert result.job_id == 7
    assert result.duration_seconds == 100.0
    assert [r.new_rank for r in result.candidates] == [1, 2]
    assert [r.original_rank for r in result.candidates] == [2, 1]
    assert [r.hook for r in result.candidates] == ["best moment", "solid audio"]
    assert [r.ai_reason for r in result.candidates] == ["strong motion spike", "loud action"]
    assert result.candidates[0].candidate is candidates[1]
    assert result.candidates[1].candidate is candidates[0]


def test_rank_highlights_passes_language_and_candidate_count(tmp_path: Path) -> None:
    candidates = [_candidate(10.0, 40.0, score=0.8, audio=0.7, motion=0.6, scene=0.3, reason="x")]
    generator = FakeGenerator(response=_ranking((1, "hook", "reason")))

    rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(deepseek_api_key="sk-1", youtube_metadata_language="english"),
        generator,
        transcripts_dir=tmp_path,
    )

    assert len(generator.calls) == 1
    context, language, candidate_count = generator.calls[0]
    assert language == "english"
    assert candidate_count == 1
    assert "Game: t" in context


def test_rank_highlights_reads_stored_transcript(tmp_path: Path) -> None:
    (tmp_path / "job-7-rank-1.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "segments": [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "recorded words"}],
            }
        ),
        encoding="utf-8",
    )
    candidates = [_candidate(10.0, 40.0, score=0.8, audio=0.7, motion=0.6, scene=0.3, reason="x")]
    generator = FakeGenerator(response=_ranking((1, "hook", "reason")))

    rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(),
        generator,
        transcripts_dir=tmp_path,
    )

    context = generator.calls[0][0]
    assert '"recorded words"' in context


def test_rank_highlights_falls_back_on_ai_failure(tmp_path: Path) -> None:
    candidates = _two_candidates()
    generator = FakeGenerator(response=None)

    result = rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(),
        generator,
        transcripts_dir=tmp_path,
    )

    assert result.method == "deterministic-fallback"
    assert result.ai_failure_reason is not None
    assert "simulated AI failure" in result.ai_failure_reason
    assert [r.original_rank for r in result.candidates] == [1, 2]
    assert [r.new_rank for r in result.candidates] == [1, 2]
    assert all(r.hook is None for r in result.candidates)
    assert all(r.ai_reason is None for r in result.candidates)


def test_rank_highlights_falls_back_when_no_api_key(tmp_path: Path) -> None:
    candidates = [_candidate(10.0, 40.0, score=0.8, audio=0.7, motion=0.6, scene=0.3, reason="x")]
    generator = FakeGenerator(response=_ranking((1, "hook", "reason")))

    result = rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(deepseek_api_key=""),
        generator,
        transcripts_dir=tmp_path,
    )

    assert result.method == "deterministic-fallback"
    assert result.ai_failure_reason is not None
    assert "API key" in result.ai_failure_reason
    assert generator.calls == []  # never invoked without a key


def test_rank_highlights_rejects_empty_candidates(tmp_path: Path) -> None:
    with pytest.raises(HighlightRankingError, match="No candidates to rank"):
        rank_highlights(
            7,
            "t",
            100.0,
            [],
            FakeSettings(),
            FakeGenerator(response=None),
            transcripts_dir=tmp_path,
        )


# ---------------------------------------------------------------------------
# Ranking report persistence
# ---------------------------------------------------------------------------


def test_rank_highlights_falls_back_on_partial_coverage(tmp_path: Path) -> None:
    candidates = _two_candidates()
    generator = FakeGenerator(response=_ranking((1, "only one", "missing the rest")))

    result = rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(),
        generator,
        transcripts_dir=tmp_path,
    )

    assert result.method == "deterministic-fallback"
    assert result.ai_failure_reason is not None
    assert [r.original_rank for r in result.candidates] == [1, 2]
    assert all(r.hook is None for r in result.candidates)


def test_write_ranking_file_writes_expected_report(tmp_path: Path) -> None:
    candidates = _two_candidates()
    generator = FakeGenerator(
        response=_ranking(
            (2, "best moment", "strong motion spike"),
            (1, "solid opener", "good audio"),
        )
    )

    result = rank_highlights(
        7,
        "Fortnite 2026-08-07 23-14-11",
        100.0,
        candidates,
        FakeSettings(),
        generator,
        transcripts_dir=tmp_path,
    )
    rankings_dir = tmp_path / "rankings"
    out_path = write_ranking_file(result, rankings_dir)

    assert out_path == rankings_dir / "job-7.json"
    assert out_path.is_file()
    assert not list(rankings_dir.glob("*.tmp"))

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 1
    assert payload["job_id"] == 7
    assert payload["source_title"] == "Fortnite 2026-08-07 23-14-11"
    assert payload["duration_seconds"] == 100.0
    assert payload["method"] == "ai"
    assert payload["ai_failure_reason"] is None
    assert len(payload["candidates"]) == 2
    first = payload["candidates"][0]
    assert first["new_rank"] == 1
    assert first["original_rank"] == 2
    assert first["start_seconds"] == 50.0
    assert first["end_seconds"] == 80.0
    assert first["hook"] == "best moment"
    assert first["ai_reason"] == "strong motion spike"
    assert set(first) >= {"score", "audio_score", "motion_score", "scene_signal", "reason"}


def test_write_ranking_file_fallback_report_has_no_hooks(tmp_path: Path) -> None:
    candidates = [_candidate(10.0, 40.0, score=0.8, audio=0.7, motion=0.6, scene=0.3, reason="x")]
    result = rank_highlights(
        7,
        "t",
        100.0,
        candidates,
        FakeSettings(deepseek_api_key=""),
        FakeGenerator(response=None),
        transcripts_dir=tmp_path,
    )

    out_path = write_ranking_file(result, tmp_path / "rankings")

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["method"] == "deterministic-fallback"
    assert payload["candidates"][0]["hook"] is None
    assert payload["candidates"][0]["ai_reason"] is None
