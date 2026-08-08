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
from moviepy import VideoFileClip  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402


class FakeRepository:
    """Only implements `running()` and `get_job()` - the only two calls
    highlight-cut is allowed to make. Any attempt by the CLI to call a
    mutating method (approve_rights, claim_job, enqueue_*, mark_*, ...)
    raises AttributeError, which fails the test - that absence is itself
    the proof of read-only, no-job-state-mutation behavior.
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


def _make_fake_settings(work_dir: Path) -> type:
    class FakeSettings:
        def __init__(self) -> None:
            self.database_url = "postgresql://user:pw@fake-host/db"
            self.max_job_attempts = 3
            self.work_dir = work_dir

    return FakeSettings


def _patch(monkeypatch: pytest.MonkeyPatch, repo: FakeRepository, work_dir: Path) -> None:
    monkeypatch.setattr(cli_module, "Settings", _make_fake_settings(work_dir))
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)


def _explode_content_engine(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("highlight-cut must never construct ContentEngine")


@pytest.fixture(scope="module")
def analyzable_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~20s synthetic clip: 10s of black/silence, then 10s of a moving test
    pattern with a 440Hz tone - long enough to clear the default 15s
    minimum clip duration and produce a real scene cut + signal spike."""
    out = tmp_path_factory.mktemp("highlight_cut_cli") / "analyzable.mp4"
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
# Rejections (no video processing / cutting should even start)
# ---------------------------------------------------------------------------


def test_rejects_unconfirmed_rights_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path="/tmp/whatever.mp4", rights_confirmed=False)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "1", "--rank", "1"])

    assert result.exit_code != 0
    assert "rights" in result.output.lower()


def test_rejects_job_with_no_local_source_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=2, source_path=None, rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "2", "--rank", "1"])

    assert result.exit_code != 0
    assert "local source_path" in result.output


def test_rejects_missing_source_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=3, source_path=str(tmp_path / "gone.mp4"), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "3", "--rank", "1"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_rejects_invalid_rank_cleanly(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "8", "--rank", "999"])

    assert result.exit_code != 0
    assert "out of range" in result.output


def test_rejects_zero_rank(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "8", "--rank", "0"])

    assert result.exit_code != 0
    assert repo.get_job_calls == []


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_successful_cut_produces_output_matching_scan_rank(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    runner = CliRunner()
    scan_result = runner.invoke(cli_app, ["highlight-scan", "8", "--top", "1", "--json"])
    assert scan_result.exit_code == 0, scan_result.output
    scan_candidate = json.loads(scan_result.output)["candidates"][0]

    original_bytes = analyzable_video.stat().st_size
    original_mtime = analyzable_video.stat().st_mtime

    cut_result = runner.invoke(cli_app, ["highlight-cut", "8", "--rank", "1"])

    assert cut_result.exit_code == 0, cut_result.output
    assert "Job 8" in cut_result.output
    assert "Rank: 1" in cut_result.output

    # source file remains unchanged
    assert analyzable_video.stat().st_size == original_bytes
    assert analyzable_video.stat().st_mtime == original_mtime

    # selected rank maps to the same candidate highlight-scan reported
    output_line = next(
        line for line in cut_result.output.splitlines() if line.startswith("Output path:")
    )
    output_path = Path(output_line.split("Output path:", 1)[1].strip())
    assert output_path.is_file()
    assert output_path.stat().st_size > 0

    with VideoFileClip(str(output_path)) as produced:
        expected_duration = scan_candidate["end_seconds"] - scan_candidate["start_seconds"]
        assert produced.duration == pytest.approx(expected_duration, abs=0.5)


def test_never_constructs_content_engine(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")
    monkeypatch.setattr(cli_module, "ContentEngine", _explode_content_engine)

    result = CliRunner().invoke(cli_app, ["highlight-cut", "8", "--rank", "1"])

    assert result.exit_code == 0, result.output


def test_only_calls_get_job_never_a_mutation_method(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path / "work")

    result = CliRunner().invoke(cli_app, ["highlight-cut", "8", "--rank", "1"])

    assert result.exit_code == 0, result.output
    assert repo.get_job_calls == [8]
    # FakeRepository defines no mutation methods at all - if the CLI had
    # called one (claim_job, mark_rendered, approve_rights, ...), invoke()
    # above would have raised AttributeError and exit_code would not be 0.


def test_refuses_to_overwrite_existing_output(
    monkeypatch: pytest.MonkeyPatch, analyzable_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path=str(analyzable_video), rights_confirmed=True)
    work_dir = tmp_path / "work"
    _patch(monkeypatch, repo, work_dir)

    runner = CliRunner()
    scan_result = runner.invoke(cli_app, ["highlight-scan", "8", "--top", "1", "--json"])
    assert scan_result.exit_code == 0, scan_result.output
    scan_candidate = json.loads(scan_result.output)["candidates"][0]

    expected_filename = cli_module._highlight_cut_filename(
        8, 1, scan_candidate["start_seconds"], scan_candidate["end_seconds"]
    )
    output_dir = work_dir / "highlights"
    output_dir.mkdir(parents=True)
    collision_path = output_dir / expected_filename
    collision_path.write_bytes(b"pre-existing file, must not be clobbered")

    result = runner.invoke(cli_app, ["highlight-cut", "8", "--rank", "1"])

    assert result.exit_code != 0
    assert collision_path.read_bytes() == b"pre-existing file, must not be clobbered"
