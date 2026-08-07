from __future__ import annotations

import inspect
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

import robin_content_engine.capture_scan as capture_scan_module  # noqa: E402
from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.capture_scan import (  # noqa: E402
    CaptureScanError,
    scan_captures,
)
from robin_content_engine.cli import app as cli_app  # noqa: E402

FAST_STABILITY_WAIT = 0.01


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self.next_id = 1
        self.enqueue_calls: list[tuple[str, str, str]] = []

    @contextmanager
    def running(self):
        yield self

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(job) for job in self.jobs.values()]

    def enqueue_local(self, source_path: Path, source_title: str, rights_note: str) -> int:
        resolved = source_path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Source file does not exist: {resolved}")
        job_id = self.next_id
        self.next_id += 1
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": str(resolved),
            "source_title": source_title,
            "rights_note": rights_note,
            "status": "pending",
        }
        self.enqueue_calls.append((str(resolved), source_title, rights_note))
        return job_id


def _write(path: Path, content: bytes = b"fake-video-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_discovers_supported_mp4(tmp_path: Path) -> None:
    _write(tmp_path / "Fortnite 2026-08-07 23-14-11.mp4")
    repo = FakeRepository()

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.videos_discovered == 1
    assert result.new_registered == 1
    assert len(repo.jobs) == 1


def test_ignores_screenshots(tmp_path: Path) -> None:
    _write(tmp_path / "clip.mp4")
    _write(tmp_path / "screenshot.png")
    _write(tmp_path / "screenshot.jpg")
    repo = FakeRepository()

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.videos_discovered == 1
    assert result.new_registered == 1
    assert result.skipped_unsupported == 2


def test_ignores_unsupported_extension(tmp_path: Path) -> None:
    _write(tmp_path / "clip.avi")
    _write(tmp_path / "notes.txt")
    repo = FakeRepository()

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.videos_discovered == 0
    assert result.skipped_unsupported == 2
    assert len(repo.jobs) == 0


def test_ignores_directories(tmp_path: Path) -> None:
    (tmp_path / "subdir.mp4").mkdir()
    _write(tmp_path / "clip.mp4")
    repo = FakeRepository()

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.videos_discovered == 1
    assert result.new_registered == 1


def test_is_stable_detects_a_file_that_grows_during_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    growing = _write(tmp_path / "recording.mp4", b"partial")

    def grow_during_wait(*args: Any, **kwargs: Any) -> None:
        growing.write_bytes(b"partial-plus-more-bytes")

    monkeypatch.setattr(capture_scan_module.time, "sleep", grow_during_wait)

    assert capture_scan_module._is_stable(growing, 0.01) is False


def test_is_stable_true_for_an_unchanged_file(tmp_path: Path) -> None:
    stable = _write(tmp_path / "recording.mp4", b"final-bytes")
    assert capture_scan_module._is_stable(stable, 0.0) is True


def test_skips_incomplete_unstable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "recording.mp4", b"partial")
    repo = FakeRepository()
    monkeypatch.setattr(capture_scan_module, "_is_stable", lambda path, wait_seconds: False)

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.skipped_unstable == 1
    assert result.new_registered == 0
    assert len(repo.jobs) == 0


def test_existing_file_not_registered_twice(tmp_path: Path) -> None:
    video = _write(tmp_path / "clip.mp4")
    repo = FakeRepository()
    repo.enqueue_local(video, "clip", "already known")

    result = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert result.new_registered == 0
    assert result.already_known == 1
    assert len(repo.jobs) == 1


def test_second_full_scan_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path / "clip1.mp4")
    _write(tmp_path / "clip2.mp4")
    repo = FakeRepository()

    first = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)
    second = scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert first.new_registered == 2
    assert second.new_registered == 0
    assert second.already_known == 2
    assert len(repo.jobs) == 2


def test_original_file_remains_untouched(tmp_path: Path) -> None:
    video = _write(tmp_path / "clip.mp4", b"original-bytes-do-not-touch")
    repo = FakeRepository()

    scan_captures(tmp_path, repo, stability_wait_seconds=FAST_STABILITY_WAIT)

    assert video.is_file()
    assert video.read_bytes() == b"original-bytes-do-not-touch"


def test_nonexistent_directory_returns_safe_operator_error(tmp_path: Path) -> None:
    repo = FakeRepository()
    missing = tmp_path / "does-not-exist"

    with pytest.raises(CaptureScanError, match="does not exist"):
        scan_captures(missing, repo, stability_wait_seconds=FAST_STABILITY_WAIT)


def test_capture_scan_module_never_imports_pipeline_or_uploader() -> None:
    source = inspect.getsource(capture_scan_module)
    assert "ContentEngine" not in source
    assert "YouTubeUploader" not in source
    assert "youtube_auth" not in source
    assert "build(" not in source


# ---------------------------------------------------------------------------
# CLI (robin-engine capture-scan)
# ---------------------------------------------------------------------------


class FakeSettings:
    def __init__(self) -> None:
        self.database_url = "postgresql://fake"
        self.max_job_attempts = 3
        self.capture_source_dir = Path("/nonexistent-default-should-not-be-used")
        self.capture_stability_wait_seconds = FAST_STABILITY_WAIT


def test_cli_custom_path_overrides_configured_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "clip.mp4")
    repo = FakeRepository()

    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["capture-scan", "--path", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Capture scan completed." in result.output
    assert "Videos discovered: 1" in result.output
    assert "New captures registered: 1" in result.output
    assert len(repo.jobs) == 1


def test_cli_nonexistent_directory_is_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["capture-scan", "--path", "/definitely/does/not/exist"])

    assert result.exit_code != 0
    assert result.exception is not None
    assert len(repo.jobs) == 0


def test_cli_capture_scan_never_calls_render_or_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "clip.mp4")
    repo = FakeRepository()

    def exploding_content_engine(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("capture-scan must never construct ContentEngine")

    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)
    monkeypatch.setattr(cli_module, "ContentEngine", exploding_content_engine)

    runner = CliRunner()
    result = runner.invoke(cli_app, ["capture-scan", "--path", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert len(repo.jobs) == 1
