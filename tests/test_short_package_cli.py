from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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


def _explode(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("short-package must never construct this.")


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def valid_vertical_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """16s, exact 9:16 at the standard 1080x1920 Shorts resolution so it
    passes the CLI's real default quality gate (15-60s duration bounds,
    >=1080x1920 minimum resolution)."""
    out = tmp_path_factory.mktemp("short_package_cli_valid") / "valid.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=1080x1920:r=24:d=16",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=16000:d=16",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ]
    )
    return out


@pytest.fixture(scope="module")
def landscape_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("short_package_cli_landscape") / "landscape.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=160x90:r=24:d=16",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:r=16000:d=16",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ]
    )
    return out


def _cwd_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """short-package writes to a literal relative "work/ready/" path, so
    each test runs from its own tmp_path to keep packages isolated."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / "work" / "ready"


def test_successful_package_creates_mp4_and_manifest(
    valid_vertical_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_root = _cwd_with(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli_app, ["short-package", str(valid_vertical_video)])

    assert result.exit_code == 0, result.output
    package_dir = ready_root / valid_vertical_video.stem
    assert package_dir.is_dir()
    packaged_video = package_dir / valid_vertical_video.name
    assert packaged_video.is_file()
    assert packaged_video.stat().st_size > 0
    manifest_path = package_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["quality_gate_passed"] is True


def test_manifest_sha256_matches_packaged_bytes(
    valid_vertical_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_root = _cwd_with(monkeypatch, tmp_path)

    CliRunner().invoke(cli_app, ["short-package", str(valid_vertical_video)])

    package_dir = ready_root / valid_vertical_video.stem
    packaged_video = package_dir / valid_vertical_video.name
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(packaged_video.read_bytes()).hexdigest()
    assert manifest["byte_size"] == packaged_video.stat().st_size


def test_packaging_refuses_failed_gate(
    landscape_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_root = _cwd_with(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli_app, ["short-package", str(landscape_video)])

    assert result.exit_code != 0
    assert not ready_root.exists()


def test_package_refuses_overwrite(
    valid_vertical_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_root = _cwd_with(monkeypatch, tmp_path)
    runner = CliRunner()

    first = runner.invoke(cli_app, ["short-package", str(valid_vertical_video)])
    assert first.exit_code == 0, first.output
    manifest_path = ready_root / valid_vertical_video.stem / "manifest.json"
    original_manifest_bytes = manifest_path.read_bytes()

    second = runner.invoke(cli_app, ["short-package", str(valid_vertical_video)])

    assert second.exit_code != 0
    assert manifest_path.read_bytes() == original_manifest_bytes


def test_source_artifact_unchanged_after_packaging(
    valid_vertical_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cwd_with(monkeypatch, tmp_path)
    original_size = valid_vertical_video.stat().st_size
    original_mtime = valid_vertical_video.stat().st_mtime

    CliRunner().invoke(cli_app, ["short-package", str(valid_vertical_video)])

    assert valid_vertical_video.stat().st_size == original_size
    assert valid_vertical_video.stat().st_mtime == original_mtime


def test_never_constructs_settings_job_repository_or_content_engine(
    valid_vertical_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cwd_with(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_module, "Settings", _explode)
    monkeypatch.setattr(cli_module, "JobRepository", _explode)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode)

    result = CliRunner().invoke(cli_app, ["short-package", str(valid_vertical_video)])

    assert result.exit_code == 0, result.output
