from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import click  # noqa: E402
import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.clip_selector import HighlightCandidate  # noqa: E402
from robin_content_engine.models import CandidateRankingResult, RankedCandidateResult  # noqa: E402
from robin_content_engine.scene_detector import SceneBoundary  # noqa: E402

SECRET_SENTINEL = "sk-do-not-print-this-secret"


class FakeRepository:
    """Only implements running() and get_job() - the only calls
    highlight-rank is allowed to make. Any attempt to call a mutating
    method (approve_rights, claim_job, enqueue_*, mark_*, ...) raises
    AttributeError, which fails the test - that absence is itself the proof
    of read-only behavior."""

    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self.get_job_calls: list[int] = []

    @contextmanager
    def running(self):
        yield self

    def seed(
        self,
        *,
        job_id: int,
        source_path: str,
        rights_confirmed: bool = True,
        source_title: str = "Fortnite 2026-08-07 23-14-11",
    ) -> None:
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": source_title,
            "rights_confirmed": rights_confirmed,
        }

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        self.get_job_calls.append(job_id)
        job = self.jobs.get(job_id)
        return dict(job) if job else None


class FakeSettings:
    def __init__(self, work_dir: Path) -> None:
        self.database_url = f"postgresql://user:{SECRET_SENTINEL}@fake-host/db"
        self.max_job_attempts = 3
        self.deepseek_api_key = "sk-fake-not-real-key"
        self.deepseek_base_url = "https://example.test"
        self.deepseek_model = "fake-model"
        self.youtube_metadata_language = "arabic"
        self.work_dir = work_dir


class FakeGenerator:
    def __init__(self, response: CandidateRankingResult) -> None:
        self.response = response
        self.last_context: str | None = None
        self.last_language: str | None = None
        self.last_candidate_count: int | None = None

    def rank_candidates(
        self, context: str, language: str, *, candidate_count: int
    ) -> CandidateRankingResult:
        self.last_context = context
        self.last_language = language
        self.last_candidate_count = candidate_count
        return self.response


class FailingGenerator:
    def rank_candidates(
        self, context: str, language: str, *, candidate_count: int
    ) -> CandidateRankingResult:
        raise RuntimeError("simulated network failure")


def _candidates() -> list[HighlightCandidate]:
    return [
        HighlightCandidate(
            start_seconds=10.0,
            end_seconds=40.0,
            score=0.8,
            audio_score=0.7,
            motion_score=0.6,
            scene_signal=0.3,
            reason="high audio spike",
        ),
        HighlightCandidate(
            start_seconds=50.0,
            end_seconds=80.0,
            score=0.9,
            audio_score=0.4,
            motion_score=0.9,
            scene_signal=0.4,
            reason="high motion",
        ),
    ]


def _scenes() -> list[SceneBoundary]:
    return [SceneBoundary(start_seconds=0.0, end_seconds=100.0, start_frame=0, end_frame=100)]


def _ranking() -> CandidateRankingResult:
    return CandidateRankingResult(
        ranking=[
            RankedCandidateResult(candidate=2, hook="best part", reason="loudest moment"),
            RankedCandidateResult(candidate=1, hook="solid opener", reason="good audio"),
        ]
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    repo: FakeRepository,
    work_dir: Path,
    generator: Any,
) -> None:
    monkeypatch.setattr(cli_module, "Settings", lambda: FakeSettings(work_dir))
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)
    monkeypatch.setattr(
        cli_module,
        "_run_highlight_analysis",
        lambda video_path, top_n: (_scenes(), _candidates()),
    )
    monkeypatch.setattr(cli_module, "ContentGenerator", lambda *a, **kw: generator)


# ---------------------------------------------------------------------------
# Rejections (no analysis should even run)
# ---------------------------------------------------------------------------


def test_rejects_nonexistent_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "999"])

    assert result.exit_code != 0
    assert repo.get_job_calls == [999]


def test_rejects_unconfirmed_rights_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(source), rights_confirmed=False)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "1"])

    assert result.exit_code != 0
    assert "rights" in result.output.lower()


def test_rejects_missing_source_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(tmp_path / "gone.mp4"), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "1"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_rejects_zero_top(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(source), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "1", "--top", "0"])

    assert result.exit_code != 0
    # typer colorizes the option name in the "Invalid value" message with
    # ANSI codes split across the string (e.g. `\x1b[1;36m-\x1b[0m\x1b[1;36m-top\x1b[0m`),
    # so the literal substring "--top" is NOT present when color is enabled
    # (as on CI). Assert on the unstyled message instead.
    assert "must be >= 1." in click.unstyle(result.output)


# ---------------------------------------------------------------------------
# Read-only behavior
# ---------------------------------------------------------------------------


def test_only_calls_get_job_never_a_mutation_method(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8"])

    assert result.exit_code == 0, result.output
    assert repo.get_job_calls == [8]


def test_no_secret_values_in_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8", "--json"])

    assert SECRET_SENTINEL not in result.output


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_writes_ranking_and_reports_ai_method(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    generator = FakeGenerator(_ranking())
    _patch(monkeypatch, repo, tmp_path, generator)

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8"])

    assert result.exit_code == 0, result.output
    assert "Method: ai" in result.output
    assert "#1 (was #2)" in result.output
    assert "#2 (was #1)" in result.output
    assert "hook: best part" in result.output

    ranking_file = tmp_path / "rankings" / "job-8.json"
    assert ranking_file.is_file()
    payload = json.loads(ranking_file.read_text(encoding="utf-8"))
    assert payload["method"] == "ai"
    assert [c["original_rank"] for c in payload["candidates"]] == [2, 1]
    assert [c["hook"] for c in payload["candidates"]] == ["best part", "solid opener"]


def test_transcript_is_read_into_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "job-8-rank-1.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "segments": [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "recorded words"}],
            }
        ),
        encoding="utf-8",
    )
    generator = FakeGenerator(_ranking())
    _patch(monkeypatch, repo, tmp_path, generator)

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8"])

    assert result.exit_code == 0, result.output
    assert generator.last_context is not None
    assert '"recorded words"' in generator.last_context
    assert "Candidate 1" in generator.last_context
    assert generator.last_candidate_count == 2


def test_json_output_matches_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FakeGenerator(_ranking()))

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["job_id"] == 8
    assert payload["method"] == "ai"
    assert payload["ai_failure_reason"] is None
    assert "output_path" in payload
    assert len(payload["candidates"]) == 2
    first = payload["candidates"][0]
    assert first["new_rank"] == 1
    assert first["original_rank"] == 2
    assert set(first["signals"].keys()) == {"audio", "motion", "scene"}
    assert first["hook"] == "best part"


# ---------------------------------------------------------------------------
# Deterministic fallback on any AI failure
# ---------------------------------------------------------------------------


def test_falls_back_to_score_order_on_ai_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    source.write_text("dummy", encoding="utf-8")
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(source), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path, FailingGenerator())

    result = CliRunner().invoke(cli_app, ["highlight-rank", "8", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["method"] == "deterministic-fallback"
    assert payload["ai_failure_reason"] is not None
    assert [c["original_rank"] for c in payload["candidates"]] == [1, 2]
    assert all(c["hook"] is None for c in payload["candidates"])
    assert all(c["ai_reason"] is None for c in payload["candidates"])
