from __future__ import annotations

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
    raise AssertionError("short-qc must never construct this.")


@pytest.fixture(scope="module")
def valid_vertical_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~16s, exact 9:16 (90x160) - fits the CLI's real default 15-60s
    duration bounds and should PASS every check."""
    out = tmp_path_factory.mktemp("short_qc_cli") / "valid.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=90x160:r=24:d=16",
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
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return out


def test_pass_exits_zero_and_prints_pass(valid_vertical_video: Path) -> None:
    result = CliRunner().invoke(cli_app, ["short-qc", str(valid_vertical_video)])

    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    assert "[PASS] file_exists" in result.output


def test_nonexistent_file_exits_nonzero_and_lists_failure(tmp_path: Path) -> None:
    missing = tmp_path / "gone.mp4"

    result = CliRunner().invoke(cli_app, ["short-qc", str(missing)])

    assert result.exit_code != 0
    assert "FAIL" in result.output
    assert "[FAIL] file_exists" in result.output


def test_json_output_contract(valid_vertical_video: Path) -> None:
    result = CliRunner().invoke(cli_app, ["short-qc", str(valid_vertical_video), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["path"] == str(valid_vertical_video)
    assert isinstance(payload["checks"], list)
    assert len(payload["checks"]) == 12
    for check in payload["checks"]:
        assert set(check.keys()) == {"name", "passed", "detail"}
    media = payload["media"]
    assert set(media.keys()) == {
        "duration_seconds",
        "width",
        "height",
        "fps",
        "has_audio",
    }
    assert media["width"] == 90
    assert media["height"] == 160


def test_json_output_on_failure_still_valid_json(tmp_path: Path) -> None:
    missing = tmp_path / "gone.mp4"

    result = CliRunner().invoke(cli_app, ["short-qc", str(missing), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["passed"] is False


def test_does_not_modify_inspected_file(valid_vertical_video: Path) -> None:
    original_size = valid_vertical_video.stat().st_size
    original_mtime = valid_vertical_video.stat().st_mtime

    CliRunner().invoke(cli_app, ["short-qc", str(valid_vertical_video)])

    assert valid_vertical_video.stat().st_size == original_size
    assert valid_vertical_video.stat().st_mtime == original_mtime


def test_never_constructs_settings_job_repository_or_content_engine(
    valid_vertical_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "Settings", _explode)
    monkeypatch.setattr(cli_module, "JobRepository", _explode)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode)

    result = CliRunner().invoke(cli_app, ["short-qc", str(valid_vertical_video)])

    assert result.exit_code == 0, result.output
