from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402

SECRET_SENTINEL = "sk-do-not-print-this-secret"


class FakeRepository:
    """Only implements `running()` and `get_job()` - the only two calls
    highlight-scan is allowed to make. Any attempt by the CLI to call a
    mutating method (approve_rights, claim_job, enqueue_*, mark_*, ...)
    raises AttributeError, which fails the test - that absence is itself
    the proof of read-only behavior, mirroring how narrowly the real
    JobRepository call is scoped in cli.py.
    """

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
        source_path: str | None,
        rights_confirmed: bool = True,
        source_title: str = "clip",
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
    def __init__(self) -> None:
        self.database_url = f"postgresql://user:{SECRET_SENTINEL}@fake-host/db"
        self.max_job_attempts = 3


def _patch(monkeypatch: pytest.MonkeyPatch, repo: FakeRepository) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)


def _explode_content_engine(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("highlight-scan must never construct ContentEngine")


@pytest.fixture(scope="module")
def analyzable_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~20s synthetic clip: 10s of black/silence, then 10s of a moving test
    pattern with a 440Hz tone - long enough to clear the default 15s
    minimum clip duration and produce a real scene cut + signal spike."""
    out = tmp_path_factory.mktemp("highlight_cli") / "analyzable.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:r=10:d=10",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono:d=10",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=64x64:r=10:d=10",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:r=16000:d=10",
        "-filter_complex",
        "[0:v][2:v]concat=n=2:v=1:a=0[vout];[1:a][3:a]concat=n=2:v=0:a=1[aout]",
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return out


# ---------------------------------------------------------------------------
# Rejections (no video processing should even start)
# ---------------------------------------------------------------------------


def test_rejects_nonexistent_job(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "999"])

    assert result.exit_code != 0
    assert repo.get_job_calls == [999]


def test_rejects_unconfirmed_rights_job(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path="/tmp/whatever.mp4", rights_confirmed=False)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "1"])

    assert result.exit_code != 0
    assert "rights" in result.output.lower()


def test_rejects_job_with_no_local_source_path(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.seed(job_id=2, source_path=None, rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "2"])

    assert result.exit_code != 0
    assert "local source_path" in result.output


def test_rejects_missing_source_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=3, source_path=str(tmp_path / "gone.mp4"), rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "3"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_never_constructs_content_engine(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode_content_engine)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8"])

    assert result.exit_code == 0, result.output


def test_only_calls_get_job_never_a_mutation_method(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8"])

    assert result.exit_code == 0, result.output
    assert repo.get_job_calls == [8]
    # FakeRepository defines no mutation methods at all - if the CLI had
    # called one, invoke() above would have raised AttributeError and
    # exit_code would not be 0. This assertion documents that intent.


def test_no_secret_values_in_output(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8", "--json"])

    assert SECRET_SENTINEL not in result.output


# ---------------------------------------------------------------------------
# JSON contract
# ---------------------------------------------------------------------------


def test_json_output_matches_contract(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=8,
        source_path=str(analyzable_video),
        source_title="Fortnite 2026-08-07 23-14-11",
        rights_confirmed=True,
    )
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8", "--top", "3", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["job_id"] == 8
    assert payload["source_title"] == "Fortnite 2026-08-07 23-14-11"
    assert payload["duration_seconds"] == pytest.approx(20.0, abs=0.5)
    assert isinstance(payload["candidates"], list)
    assert len(payload["candidates"]) <= 3
    assert len(payload["candidates"]) >= 1  # this fixture has a real, findable spike

    for rank, candidate in enumerate(payload["candidates"], start=1):
        assert candidate["rank"] == rank
        assert candidate["end_seconds"] > candidate["start_seconds"]
        assert candidate["duration_seconds"] == pytest.approx(
            candidate["end_seconds"] - candidate["start_seconds"], abs=1e-6
        )
        assert set(candidate["signals"].keys()) == {"audio", "motion", "scene"}
        assert isinstance(candidate["reason"], str) and candidate["reason"]


def test_top_option_limits_candidate_count(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8", "--top", "1", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["candidates"]) <= 1


def test_human_readable_output_is_not_json(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["highlight-scan", "8"])

    assert result.exit_code == 0, result.output
    assert "Job 8" in result.output
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)
