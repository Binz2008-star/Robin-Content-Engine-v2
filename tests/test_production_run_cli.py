from __future__ import annotations

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
from robin_content_engine.quality_gate import QualityGateResult  # noqa: E402
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402
from robin_content_engine.youtube_auth import ChannelIdentity  # noqa: E402


class FakeRepository:
    """Only implements `running()` and `get_job()` - the only two calls
    production-run is allowed to make."""

    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self.get_job_calls: list[int] = []

    @contextmanager
    def running(self):
        yield self

    def seed(
        self, *, job_id: int, source_path: str | None, rights_confirmed: bool = True
    ) -> None:
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": "clip",
            "rights_confirmed": rights_confirmed,
        }

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        self.get_job_calls.append(job_id)
        job = self.jobs.get(job_id)
        return dict(job) if job else None


class FakeRecognizer:
    instances: ClassVar[list[FakeRecognizer]] = []

    def __init__(self, *, model_size: str = "base", **_kwargs: Any) -> None:
        self.model_size = model_size
        FakeRecognizer.instances.append(self)

    def transcribe(self, media_path: Path) -> list[TranscriptSegment]:
        return [TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there")]


class FakeSettings:
    def __init__(self, work_dir: Path, expected_channel_id: str | None = "UC_expected") -> None:
        self.database_url = "postgresql://user:pw@fake-host/db"
        self.max_job_attempts = 3
        self.work_dir = work_dir
        self.youtube_client_secret_file = Path("client_secret.json")
        self.youtube_token_file = Path("token.json")
        self.youtube_category_id = "20"
        self.youtube_expected_channel_id = expected_channel_id
        self.youtube_privacy_status = "public"  # deliberately not "private"


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
    raise AssertionError("this must never be constructed by production-run in this test.")


def _patch(monkeypatch: pytest.MonkeyPatch, repo: FakeRepository, tmp_path: Path) -> None:
    # production-run's package step defaults to the same literal relative
    # "work/ready/" root as short-package (deliberately not
    # Settings.work_dir-relative - see cli.py/production_runner.py), so
    # each test must run from its own isolated cwd or repeated runs
    # collide on the same real work/ready/ directory (and, worse, on
    # already-written upload_attempt.json/upload_receipt.json markers).
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "Settings", lambda: FakeSettings(tmp_path / "work"))
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)
    monkeypatch.setattr(pr_module, "FasterWhisperRecognizer", FakeRecognizer)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode)
    FakeRecognizer.instances.clear()


def _patch_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    monkeypatch.setattr(cli_module, "YouTubeUploader", FakeUploader)
    FakeUploader.captured_kwargs = {}
    FakeUploader.upload_calls = []


@pytest.fixture(scope="module")
def analyzable_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~20s continuous bright pattern (never black) + 10s silence then
    10s tone - same design as test_production_runner.py's fixture, so
    the reframed output never fails a black-frame check regardless of
    which >=15s window highlight-scan selects."""
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


# ---------------------------------------------------------------------------
# Success without publishing
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


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def test_production_run_title_without_description_fails(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=3, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(
        cli_app, ["production-run", "3", "--title", "Only Title"]
    )

    assert result.exit_code != 0
    assert "--description" in result.output
    assert repo.get_job_calls == []


def test_production_run_execute_upload_without_title_fails(
    analyzable_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=4, source_path=str(analyzable_video))
    _patch(monkeypatch, repo, tmp_path)

    result = CliRunner().invoke(
        cli_app, ["production-run", "4", "--execute-private-upload"]
    )

    assert result.exit_code != 0
    assert repo.get_job_calls == []


# ---------------------------------------------------------------------------
# Publish dry-run wiring
# ---------------------------------------------------------------------------


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
        [
            "production-run",
            "5",
            "--title",
            "A Title",
            "--description",
            "A description.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "PUBLISH DRY RUN PASS" in result.output
    assert "Privacy: private" in result.output


# ---------------------------------------------------------------------------
# Real (fake) upload wiring: privacy hard-coded, exactly one call, no
# real network access
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# QC failure routing (exit 1, no package line, publish never attempted)
# ---------------------------------------------------------------------------


def test_production_run_quality_gate_failure_exits_nonzero_and_skips_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=8, source_path="/tmp/whatever.mp4")
    _patch(monkeypatch, repo, tmp_path)
    _patch_youtube(monkeypatch)

    from robin_content_engine.quality_gate import MediaMetadata, QualityCheck

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
        quality_gate=QualityGateResult(
            passed=False,
            checks=[QualityCheck(name="duration_within_bounds", passed=False, detail="too short")],
            media=MediaMetadata(None, None, None, None, None),
        ),
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
