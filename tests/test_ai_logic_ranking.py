from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.ai_logic import (  # noqa: E402
    CLICKBAIT_MARKERS,
    ContentGenerationError,
    ContentGenerator,
    validate_ranking_coverage,
    validate_ranking_hooks,
)
from robin_content_engine.models import (  # noqa: E402
    CandidateRankingResult,
    RankedCandidateResult,
)


def _ranking(*entries: tuple[int, str, str]) -> CandidateRankingResult:
    return CandidateRankingResult(
        ranking=[
            RankedCandidateResult(candidate=candidate_id, hook=hook, reason=reason)
            for candidate_id, hook, reason in entries
        ]
    )


def _generator(monkeypatch: pytest.MonkeyPatch, content: str) -> ContentGenerator:
    generator = ContentGenerator(
        api_key="sk-fake-not-real-key", base_url="https://example.test", model="fake-model"
    )

    def fake_create(**kwargs: Any) -> SimpleNamespace:
        assert kwargs["response_format"] == {"type": "json_object"}
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(generator.client.chat.completions, "create", fake_create)
    return generator


# ---------------------------------------------------------------------------
# Deterministic coverage validation
# ---------------------------------------------------------------------------


def test_validate_ranking_coverage_accepts_full_permutation() -> None:
    validate_ranking_coverage(_ranking((3, "aa", "r"), (1, "bb", "r"), (2, "cc", "r")), 3)


def test_validate_ranking_coverage_rejects_partial() -> None:
    with pytest.raises(ContentGenerationError, match="2 of 3"):
        validate_ranking_coverage(_ranking((1, "aa", "r"), (2, "bb", "r")), 3)


def test_validate_ranking_coverage_rejects_duplicate() -> None:
    with pytest.raises(ContentGenerationError, match="more than once"):
        validate_ranking_coverage(_ranking((1, "aa", "r"), (1, "bb", "r")), 2)


def test_validate_ranking_coverage_rejects_out_of_range() -> None:
    with pytest.raises(ContentGenerationError, match="outside"):
        validate_ranking_coverage(_ranking((4, "aa", "r"), (1, "bb", "r")), 3)


def test_validate_ranking_coverage_rejects_zero_count() -> None:
    empty = CandidateRankingResult.model_construct(ranking=[])
    with pytest.raises(ContentGenerationError, match="candidate_count"):
        validate_ranking_coverage(empty, 0)


# ---------------------------------------------------------------------------
# Hook safety validation
# ---------------------------------------------------------------------------


def test_validate_ranking_hooks_rejects_banned_phrase() -> None:
    banned = CLICKBAIT_MARKERS[0]
    with pytest.raises(ContentGenerationError, match="banned phrase"):
        validate_ranking_hooks(_ranking((1, f"try this {banned}", "r")))


def test_validate_ranking_hooks_accepts_clean_hooks() -> None:
    validate_ranking_hooks(_ranking((1, "let's go", "r"), (2, "watch this", "r")))


# ---------------------------------------------------------------------------
# JSON contract of _complete_ranking (single attempt, no retry)
# ---------------------------------------------------------------------------


def test_complete_ranking_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    content = json.dumps(
        {
            "ranking": [
                {"candidate": 2, "hook": "best part", "reason": "loudest"},
                {"candidate": 1, "hook": "solid opener", "reason": "good audio"},
            ]
        }
    )
    generator = _generator(monkeypatch, content)

    ranking = generator._complete_ranking(
        [{"role": "user", "content": "context"}], candidate_count=2
    )

    assert len(ranking.ranking) == 2
    assert ranking.ranking[0].candidate == 2
    assert ranking.ranking[0].hook == "best part"
    assert ranking.ranking[1].candidate == 1


def test_complete_ranking_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mirrors the existing _complete() pattern: an unparseable response
    # escapes as json.JSONDecodeError (a retryable error type); the
    # caller's fallback catches it like any other AI failure.
    generator = _generator(monkeypatch, "{not valid json")

    with pytest.raises(json.JSONDecodeError):
        generator._complete_ranking([{"role": "user", "content": "context"}], candidate_count=1)


def test_complete_ranking_rejects_partial_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    content = json.dumps(
        {"ranking": [{"candidate": 1, "hook": "only one", "reason": "missing the rest"}]}
    )
    generator = _generator(monkeypatch, content)

    with pytest.raises(ContentGenerationError, match="1 of 2"):
        generator._complete_ranking([{"role": "user", "content": "context"}], candidate_count=2)


def test_complete_ranking_rejects_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = _generator(monkeypatch, "")

    with pytest.raises(ContentGenerationError, match="empty"):
        generator._complete_ranking([{"role": "user", "content": "context"}], candidate_count=1)


def test_rank_candidates_public_method(monkeypatch: pytest.MonkeyPatch) -> None:
    content = json.dumps(
        {"ranking": [{"candidate": 1, "hook": "best part", "reason": "loudest"}]}
    )
    generator = _generator(monkeypatch, content)

    ranking = generator.rank_candidates("context", "english", candidate_count=1)

    assert ranking.ranking[0].candidate == 1
    assert ranking.ranking[0].hook == "best part"
