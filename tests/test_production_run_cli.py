from __future__ import annotations

import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine import production_runner as pr_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.models import UploadResult  # noqa: E402
from robin_content_engine.production_runner import ProductionRunResult  # noqa: E402
from robin_content_engine.quality_gate import (  # noqa: E402
    MediaMetadata,
    QualityCheck,
    QualityGateResult,
)
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402
from robin_content_engine.youtube_auth import ChannelIdentity  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self.get_job_calls: list[int] = []
        self.list_jobs_calls = 0
        self.enqueue_calls: list[dict[str, Any]] = []
        self.terminal_failures: list[tuple[int, str]] = []

    @contextmanager
    def running(self):
        yield self

    def mark_deterministic_failure(self, job_id: int, reason: str) -> bool:
        self.terminal_failures.append((job_id, reason))
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "quarantined"
            self.jobs[job_id]["last_error"] = reason
            return True
        return False

    def seed(
        self,
        *,
        job_id: int,
        source_path: str | None,
        rights_confirmed: bool = True,
        status: str = "pending",
        youtube_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": "clip",
            "rights_confirmed": rights_confirmed,
            "status": status,
            "youtube_id": youtube_id,
            "last_error": last_error,
        }
        self._next_id = max(self._next_id, job_id + 1)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        self.get_job_calls.append(job_id)
        job = self.jobs.get(job_id)
        return dict(job) if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        self.list_jobs_calls += 1
        return [dict(j) for j in self.jobs.values()]

    def enqueue_api_job(
        self, *, source_path: str, source_title: str, rights_confirmed: bool, rights_note: str
    ) -> int:
        job_id = self._next_id
        self._next_id += 1
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": source_title,
            "rights_confirmed": rights_confirmed,
            "rights_note": rights_note,
            "status": "pending",
            "youtube_id": None,
            "last_error": None,
        }
        self.enqueue_calls.append(dict(self.jobs[job_id]))
        return job_id


class FakeRecognizer:
    instances: ClassVar[list[FakeRecognizer]] = []

    def __init__(self, *, model_size: str = "base", **_kwargs: Any) -> None:
        self.model_size = model_size
        FakeRecognizer.instances.append(self)

    def transcribe(self, media_path: Path) -> list[TranscriptSegment]:
        return [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there")]


class FakeSettings:
    def __init__(
        self,
        work_dir: Path,
        capture_dir: Path,
        expected_channel_id: str | None = "UC_expected",
    ) -> None:
        self.database_url = "postgresql://user:pw@fake-host/db"
        self.max_job_attempts = 3
        self.work_dir = work_dir
        self.capture_source_dir = capture_dir
        self.capture_stability_wait_seconds = 0.0
        self.highlight_min_seconds = 15.0
        self.highlight_max_seconds = 60.0
        self.youtube_client_secret_file = Path("client_secret.json")
        self.youtube_token_file = Path("token.json")
        self.youtube_category_id = "20"
        self.youtube_expected_channel_id = expected_channel_id
        self.youtube_privacy_status = "public"  # deliberately not "private"
        self.youtube_max_uploads_per_day = 10


class FakeAuth:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def verify_current_channel(self) -> ChannelIdentity:
        return ChannelIdentity(channel_id="UC_expected", title="Test Channel", custom_url=None)


class FakeUploader:
    captured_kwargs: ClassVar[dict[str, Any]] = {}
    upload_calls: ClassVar[list[tuple[Path, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        FakeUploader.captured_kwargs = kwargs

    def upload(self, video_path: Path, content: Any) -> UploadResult:
        FakeUploader.upload_calls.append((video_path, content))
        privacy_status = self.captured_kwargs["privacy_status"]
        return UploadResult(youtube_id="videoID999", privacy_status=privacy_status)


def _explode(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("this must never be constructed in this test.")


def _patch(monkeypatch: pytest.MonkeyPatch, repo: FakeRepository, tmp_path: Path) -> None:
    # production-run/-once's package step defaults to the same literal
    # relative "work/ready/" root as short-package (deliberately not
    # Settings.work_dir-relative), so each test must run from its own
    # isolated cwd or repeated runs collide on the same real work/ready/
    # directory (and, worse, on already-written upload_attempt.json/
    # upload_receipt.json markers).
    monkeypatch.chdir(tmp_path)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        cli_module, "Settings", lambda: FakeSettings(tmp_path / "work", capture_dir)
    )
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)
    monkeypatch.setattr(pr_module, "FasterWhisperRecognizer", FakeRecognizer)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode)
    FakeRecognizer.instances.clear()


def _patch_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    monkeypatch.setattr(cli_module, "YouTubeUploader", FakeUploader)
    FakeUploader.captured_kwargs = {}
    FakeUploader.upload_calls = []


def _write_marker(
    package_dir: Path, filename: str, payload: dict[str, Any] | None = None
) -> None:
    (package_dir / filename).write_text(
        json.dumps(payload or {"status": "started"}), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def analyzable_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~20s continuous bright pattern (never black) + 10s silence then
    10s tone - the reframed output never fails a black-frame check
    regardless of which >=15s window highlight-scan selects."""
    out = tmp_path_factory.mktemp("production_run_cli") / "analyzable.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=128x64:r=10:d=20",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono:d=10",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:r=16000:d=10",
        "-filter_complex",
        "[1:a][2:a]concat=n=2:v=0:a=1[aout]",
        "-map",
        "0:v",
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


def _fake_qc_result(passed: bool) -> QualityGateResult:
    return QualityGateResult(
        passed=passed,
        checks=[QualityCheck(name="duration_within_bounds", passed=passed, detail="x")],
        media=MediaMetadata(None, None, None, None, None),
    )


# ---------------------------------------------------------------------------
# production-run: success without publish, rights rejection, metadata
# validation, publish dry-run/execute wiring, QC-failure routing.
# (see PR history for original coverage design notes)
# ---------------------------------------------------------------------------


def test_production_run_success_without_publish(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run", "1", "--rank", "1"])

    assert result.exit_code == 0, result.output
    assert "Quality gate: PASS" in result.output
    assert "Package:" in result.output
    assert "PUBLISH" not in result.output
    assert repo.get_job_calls == [1]


def test_production_run_rejects_unconfirmed_rights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=2, source_path="/tmp/whatever.mp4", rights_confirmed=False)
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run", "2"])

    assert result.exit_code != 0
    assert "rights" in result.output.lower()


def test_production_run_title_without_description_fails(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=3, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run", "3", "--title", "Only Title"])

    assert result.exit_code != 0
    # not "--description": Typer/Rich's error-panel text wrapping breaks
    # words after hyphens by default, and on a narrower detected terminal
    # width (observed on Linux CI, not reproduced locally on Windows)
    # "--description" wraps exactly at the "--"/"description" boundary,
    # so the literal hyphenated substring is not always contiguous in
    # result.output. The plain word survives regardless of wrap width.
    assert "description" in result.output
    assert repo.get_job_calls == []


def test_production_run_execute_upload_without_title_fails(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=4, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run", "4", "--execute-private-upload"])

    assert result.exit_code != 0
    assert repo.get_job_calls == []


def test_production_run_publish_dry_run_never_touches_youtube(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=5, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    result = CliRunner().invoke(
        cli_app,
        ["production-run", "5", "--title", "A Title", "--description", "A description."],
    )

    assert result.exit_code == 0, result.output
    assert "PUBLISH DRY RUN PASS" in result.output
    assert "Privacy: private" in result.output


def test_production_run_execute_upload_hardcodes_private(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=6, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "production-run",
            "6",
            "--title",
            "A Title",
            "--description",
            "A description.",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "UPLOAD SUCCESS" in result.output
    assert FakeUploader.captured_kwargs["privacy_status"] == "private"
    assert len(FakeUploader.upload_calls) == 1


def test_production_run_execute_upload_canary_no_real_google_api_client(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from robin_content_engine import uploader as uploader_module
    from robin_content_engine import youtube_auth as youtube_auth_module

    def exploding_build(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real googleapiclient.discovery.build must never be called in tests.")

    monkeypatch.setattr(uploader_module, "build", exploding_build)
    monkeypatch.setattr(youtube_auth_module, "build", exploding_build)

    repo = FakeRepository()
    repo.seed(job_id=7, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "production-run",
            "7",
            "--title",
            "A Title",
            "--description",
            "A description.",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code == 0, result.output


def test_production_run_quality_gate_failure_exits_nonzero_and_skips_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path="/tmp/whatever.mp4")
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    fake_result = ProductionRunResult(
        job_id=8,
        rank=1,
        source_title="clip",
        candidate_score=0.5,
        start_seconds=0.0,
        end_seconds=15.0,
        reframed_video_path=tmp_path / "reframed.mp4",
        has_captions=True,
        caption_segment_count=1,
        final_video_path=tmp_path / "final.mp4",
        quality_gate=_fake_qc_result(False),
        package=None,
    )
    monkeypatch.setattr(cli_module, "run_production", lambda *a, **kw: fake_result)

    result = CliRunner().invoke(
        cli_app,
        [
            "production-run",
            "8",
            "--title",
            "A Title",
            "--description",
            "A description.",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code != 0
    assert "Quality gate: FAIL" in result.output
    assert "Package:" not in result.output
    assert FakeUploader.upload_calls == []


# ---------------------------------------------------------------------------
# production-run-once
# ---------------------------------------------------------------------------


def test_production_run_once_no_eligible_job_prints_exact_phrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code == 0, result.output
    assert "NO ELIGIBLE JOB" in result.output


@pytest.mark.parametrize(
    "excluded_status", ["uploaded", "rendered", "processing", "failed", "quarantined"]
)
def test_production_run_once_excludes_non_pending_status(
    excluded_status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path="/tmp/whatever.mp4", status=excluded_status)
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code == 0, result.output
    assert "NO ELIGIBLE JOB" in result.output
    assert repo.get_job_calls == []


def test_production_run_once_processes_at_most_one_job_on_qc_failure(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    repo.seed(job_id=2, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    call_count = {"n": 0}
    original_loaded_job = pr_module._run_production_loaded_job

    def counting_loaded_job(job: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if job["id"] == 1:
            from robin_content_engine.quality_gate import QualityGateConfig

            kwargs["quality_gate_config"] = QualityGateConfig(
                min_clip_seconds=100.0, max_clip_seconds=200.0
            )
        return original_loaded_job(job, *args, **kwargs)

    monkeypatch.setattr(pr_module, "_run_production_loaded_job", counting_loaded_job)

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code != 0
    assert "Quality gate: FAIL" in result.output
    assert "quarantined" in result.output.lower()
    assert call_count["n"] == 1  # candidate 2 was never attempted
    assert len(repo.terminal_failures) == 1
    assert repo.terminal_failures[0][0] == 1


def test_production_run_once_discovers_new_capture_without_auto_approving(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo, tmp_path)
    shutil.copy(analyzable_video, tmp_path / "captures" / "new_capture.mp4")

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code == 0, result.output
    assert "New captures registered: 1" in result.output
    assert "NO ELIGIBLE JOB" in result.output
    assert len(repo.enqueue_calls) == 1
    assert repo.enqueue_calls[0]["rights_confirmed"] is False


def test_production_run_once_selects_and_publishes_dry_run_with_deterministic_metadata(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code == 0, result.output
    assert "Job 1: clip" in result.output
    assert "Title: clip — Highlight" in result.output
    assert "PUBLISH DRY RUN PASS" in result.output
    assert "Privacy: private" in result.output


def test_production_run_once_execute_upload_exactly_one_call_private(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    result = CliRunner().invoke(cli_app, ["production-run-once", "--execute-private-upload"])

    assert result.exit_code == 0, result.output
    assert "UPLOAD SUCCESS" in result.output
    assert len(FakeUploader.upload_calls) == 1
    assert FakeUploader.captured_kwargs["privacy_status"] == "private"


def test_production_run_once_execute_upload_canary_no_real_google_api_client(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from robin_content_engine import uploader as uploader_module
    from robin_content_engine import youtube_auth as youtube_auth_module

    def exploding_build(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real googleapiclient.discovery.build must never be called in tests.")

    monkeypatch.setattr(uploader_module, "build", exploding_build)
    monkeypatch.setattr(youtube_auth_module, "build", exploding_build)

    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    result = CliRunner().invoke(cli_app, ["production-run-once", "--execute-private-upload"])

    assert result.exit_code == 0, result.output


def test_production_run_once_skips_already_published_job(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    first = CliRunner().invoke(cli_app, ["production-run-once"])
    assert first.exit_code == 0, first.output
    ready_root = tmp_path / "work" / "ready"
    package_dirs = list(ready_root.glob("job-1-highlight-*"))
    assert len(package_dirs) == 1
    _write_marker(package_dirs[0], "upload_receipt.json")

    second = CliRunner().invoke(cli_app, ["production-run-once"])

    assert second.exit_code == 0, second.output
    assert "NO ELIGIBLE JOB" in second.output
    assert "already published" in second.output.lower()


def test_production_run_once_ambiguous_attempt_stops_job_no_retry(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    first = CliRunner().invoke(cli_app, ["production-run-once"])
    assert first.exit_code == 0, first.output
    ready_root = tmp_path / "work" / "ready"
    package_dirs = list(ready_root.glob("job-1-highlight-*"))
    _write_marker(package_dirs[0], "upload_attempt.json")

    second = CliRunner().invoke(cli_app, ["production-run-once"])

    assert second.exit_code == 0, second.output
    assert "NO ELIGIBLE JOB" in second.output
    assert "ambiguous" in second.output.lower()


def test_production_run_once_never_constructs_content_engine(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    result = CliRunner().invoke(cli_app, ["production-run-once"])

    assert result.exit_code == 0, result.output


def test_production_run_once_no_privacy_cli_option_exists() -> None:
    help_result = CliRunner().invoke(cli_app, ["production-run-once", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "--privacy" not in help_result.output
    assert "--public" not in help_result.output
    assert "--unlisted" not in help_result.output
    # no --title/--description option either - metadata is fully automatic
    assert "--title" not in help_result.output
    assert "--description" not in help_result.output


# ---------------------------------------------------------------------------
# production-status
# ---------------------------------------------------------------------------


def test_production_status_text_output(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video), rights_confirmed=False)
    repo.seed(job_id=2, source_path=str(analyzable_video), rights_confirmed=True)
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-status"])

    assert result.exit_code == 0, result.output
    assert "Awaiting rights: 1" in result.output
    assert "Rights-approved eligible: 1" in result.output
    assert repo.get_job_calls == []  # status uses list_jobs(), not get_job()


def test_production_status_rejected_job_not_shown_as_awaiting_rights(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(analyzable_video),
        rights_confirmed=False,
        status="quarantined",
        last_error="Rights rejected by operator.",
    )
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-status"])

    assert result.exit_code == 0, result.output
    assert "Awaiting rights: 0" in result.output
    assert "Rejected: 1" in result.output


def test_production_status_json_output(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(analyzable_video), rights_confirmed=False)
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(cli_app, ["production-status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["awaiting_rights"] == 1
    assert payload["jobs"][0]["state"] == "awaiting_rights"


def test_production_status_never_touches_youtube_or_content_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)

    result = CliRunner().invoke(cli_app, ["production-status"])

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# production-reconcile
# ---------------------------------------------------------------------------


def _reconcile_snapshot(videos: list[dict[str, Any]]) -> Any:
    from robin_content_engine.youtube_sync import (
        YouTubeChannelSnapshot,
        YouTubeSyncSnapshot,
        YouTubeVideoSnapshot,
    )

    def to_video(raw: dict[str, Any]) -> YouTubeVideoSnapshot:
        return YouTubeVideoSnapshot(
            video_id=raw["video_id"],
            channel_id="UC_expected",
            title="clip — Highlight",
            description="",
            published_at=raw["published_at"],
            duration_seconds=58,
            privacy_status=raw.get("privacy_status", "private"),
            made_for_kids=False,
            self_declared_made_for_kids=False,
            category_id="20",
            license="youtube",
            tags=(),
            thumbnail_url=None,
            view_count=None,
            like_count=None,
            comment_count=None,
        )

    return YouTubeSyncSnapshot(
        channel=YouTubeChannelSnapshot(
            channel_id="UC_expected",
            title="Test Channel",
            custom_url=None,
            description="",
            published_at=None,
            uploads_playlist_id="UU_expected",
            view_count=None,
            subscriber_count=None,
            hidden_subscriber_count=False,
            video_count=None,
        ),
        videos=tuple(to_video(v) for v in videos),
        discovered_video_count=len(videos),
    )


def test_production_reconcile_resolves_ambiguous_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_module, "Settings", lambda: FakeSettings(tmp_path / "work", tmp_path / "captures")
    )
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    started = datetime.now(UTC) - timedelta(minutes=1)

    class _ReconcileSync:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def fetch_snapshot(self) -> Any:
            return _reconcile_snapshot(
                [{"video_id": "videoID777", "published_at": started + timedelta(seconds=10)}]
            )

    monkeypatch.setattr(cli_module, "YouTubeChannelSync", _ReconcileSync)

    package_dir = tmp_path / "work" / "ready" / "job-1-highlight-01-10.0-25.0"
    package_dir.mkdir(parents=True)
    _write_marker(
        package_dir,
        "upload_attempt.json",
        {
            "format_version": 1,
            "package_sha256": "sha256-xyz",
            "expected_channel_id": "UC_expected",
            "authenticated_channel_id": "UC_expected",
            "started_at": started.isoformat(),
            "intended_privacy": "private",
            "status": "started",
        },
    )

    result = CliRunner().invoke(cli_app, ["production-reconcile"])

    assert result.exit_code == 0, result.output
    assert "RESOLVED" in result.output
    assert "videoID777" in result.output
    assert (package_dir / "upload_receipt.json").is_file()
    assert not (package_dir / "upload_attempt.json").exists()


def test_production_reconcile_unresolved_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_module, "Settings", lambda: FakeSettings(tmp_path / "work", tmp_path / "captures")
    )
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    started = datetime.now(UTC) - timedelta(hours=3)

    class _EmptySync:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def fetch_snapshot(self) -> Any:
            return _reconcile_snapshot([])

    monkeypatch.setattr(cli_module, "YouTubeChannelSync", _EmptySync)

    package_dir = tmp_path / "work" / "ready" / "job-1-highlight-01-10.0-25.0"
    package_dir.mkdir(parents=True)
    _write_marker(
        package_dir,
        "upload_attempt.json",
        {
            "format_version": 1,
            "package_sha256": "sha256-xyz",
            "authenticated_channel_id": "UC_expected",
            "started_at": started.isoformat(),
            "intended_privacy": "private",
            "status": "started",
        },
    )

    result = CliRunner().invoke(cli_app, ["production-reconcile"])

    assert result.exit_code == 1
    assert "UNRESOLVED" in result.output
    assert (package_dir / "upload_attempt.json").is_file()


def test_production_reconcile_no_ambiguous_state_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_module, "Settings", lambda: FakeSettings(tmp_path / "work", tmp_path / "captures")
    )
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)

    class _ExplodingSync:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("YouTube must not be touched when nothing is ambiguous")

        def fetch_snapshot(self) -> Any:
            raise AssertionError("YouTube must not be touched when nothing is ambiguous")

    monkeypatch.setattr(cli_module, "YouTubeChannelSync", _ExplodingSync)

    result = CliRunner().invoke(cli_app, ["production-reconcile"])

    assert result.exit_code == 0, result.output
    assert "No ambiguous upload states found" in result.output


# ---------------------------------------------------------------------------
# production-config
# ---------------------------------------------------------------------------


def test_production_config_prints_resolved_roots_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command must print the canonical roots Settings actually
    resolved against (so a launcher can verify it ran in the intended
    repository) and NEVER print secrets - no database URL, no API keys,
    no OAuth token paths."""
    work_dir = tmp_path / "work"
    capture_dir = tmp_path / "captures"
    monkeypatch.setattr(
        cli_module, "Settings", lambda: FakeSettings(work_dir, capture_dir)
    )
    monkeypatch.setattr(cli_module, "APP_ROOT", tmp_path)

    result = CliRunner().invoke(cli_app, ["production-config"])

    assert result.exit_code == 0, result.output
    assert f"Application root: {tmp_path}" in result.output
    assert f"Config file: {tmp_path / '.env'}" in result.output
    assert f"Work directory: {work_dir}" in result.output
    assert f"Capture source directory: {capture_dir}" in result.output
    assert "Python executable:" in result.output
    assert f"Source root: {tmp_path / 'src'}" in result.output
    for secret in ("postgresql://", "user:pw", "api_key", "client_secret", "token.json"):
        assert secret not in result.output
