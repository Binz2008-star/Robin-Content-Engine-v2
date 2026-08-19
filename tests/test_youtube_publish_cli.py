from __future__ import annotations

import subprocess
import sys
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
from robin_content_engine.cli import app as cli_app  # noqa: E402
from robin_content_engine.models import UploadResult  # noqa: E402
from robin_content_engine.quality_gate import package_short as real_package_short  # noqa: E402
from robin_content_engine.youtube_auth import ChannelIdentity  # noqa: E402


def _explode(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("this must never be constructed by youtube-publish-package.")


class FakeSettings:
    def __init__(self, expected_channel_id: str | None = "UC_expected") -> None:
        self.youtube_client_secret_file = Path("client_secret.json")
        self.youtube_token_file = Path("token.json")
        self.youtube_category_id = "20"
        self.youtube_expected_channel_id = expected_channel_id
        # deliberately "public" - proves the CLI hard-codes "private"
        # regardless of what environment configuration says.
        self.youtube_privacy_status = "public"


class FakeAuth:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.channel_id = "UC_expected"

    def verify_current_channel(self) -> ChannelIdentity:
        return ChannelIdentity(channel_id=self.channel_id, title="Test Channel", custom_url=None)


class FakeUploader:
    captured_kwargs: ClassVar[dict[str, Any]] = {}
    upload_calls: ClassVar[list[tuple[Path, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        FakeUploader.captured_kwargs = kwargs

    def upload(self, video_path: Path, content: Any) -> UploadResult:
        FakeUploader.upload_calls.append((video_path, content))
        privacy_status = FakeUploader.captured_kwargs["privacy_status"]
        return UploadResult(youtube_id="videoID999", privacy_status=privacy_status)


def _make_source_video(path: Path, *, duration: float = 16.0) -> Path:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=s=1080x1920:r=24:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=f=440:r=16000:d={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """16s 1080x1920 clip, packaged with the real default QualityGateConfig
    (15-60s bounds, >=1080x1920 minimum resolution) - matches what the CLI
    itself uses (no config override), so validate_package()'s fresh re-run
    at publish time genuinely re-checks the same bounds a real production
    package would face."""
    source = _make_source_video(tmp_path / "source.mp4")
    result = real_package_short(source, tmp_path / "ready")
    return result.package_dir


def _patch_settings_and_youtube(
    monkeypatch: pytest.MonkeyPatch, expected_channel_id: str | None = "UC_expected"
) -> None:
    monkeypatch.setattr(cli_module, "Settings", lambda: FakeSettings(expected_channel_id))
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    monkeypatch.setattr(cli_module, "YouTubeUploader", FakeUploader)
    FakeUploader.captured_kwargs = {}
    FakeUploader.upload_calls = []


def _patch_no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "JobRepository", _explode)
    monkeypatch.setattr(cli_module, "ContentEngine", _explode)


# ---------------------------------------------------------------------------
# 1. Valid package dry-run PASS
# ---------------------------------------------------------------------------


def test_dry_run_pass(package_dir: Path) -> None:
    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "A Real Title",
            "--description",
            "A real description.",
            "--tag",
            "gaming",
            "--tag",
            "fortnite",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN PASS" in result.output
    assert "Title: A Real Title" in result.output
    assert "Tag count: 2" in result.output
    assert "Privacy: private" in result.output


# ---------------------------------------------------------------------------
# 2. Missing package -> FAIL
# ---------------------------------------------------------------------------


def test_dry_run_missing_package_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(tmp_path / "no-such-package"),
            "--title",
            "T",
            "--description",
            "D",
        ],
    )

    assert result.exit_code != 0
    assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# 12 / 13 / 26. Dry-run never constructs YouTubeAuth/YouTubeUploader/
# JobRepository/ContentEngine; zero network calls follow from that.
# ---------------------------------------------------------------------------


def test_dry_run_never_constructs_youtube_or_db_objects(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "Settings", _explode)
    monkeypatch.setattr(cli_module, "YouTubeAuth", _explode)
    monkeypatch.setattr(cli_module, "YouTubeUploader", _explode)
    _patch_no_db(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "T",
            "--description",
            "D",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN PASS" in result.output


# ---------------------------------------------------------------------------
# 18. Uploader always receives privacy="private" (never inherited from
# environment configuration, which here is deliberately "public")
# ---------------------------------------------------------------------------


def test_execute_upload_hardcodes_private_privacy(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings_and_youtube(monkeypatch)
    _patch_no_db(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "T",
            "--description",
            "D",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code == 0, result.output
    assert FakeUploader.captured_kwargs["privacy_status"] == "private"
    assert "Privacy: private" in result.output


# ---------------------------------------------------------------------------
# 19. No public/unlisted CLI option exists
# ---------------------------------------------------------------------------


def test_no_privacy_cli_option_exists(package_dir: Path) -> None:
    # The command's own help text legitimately explains that public/unlisted
    # are NOT selectable - so this checks the actual option surface (no
    # --privacy/--public/--unlisted flag exists), not prose substrings.
    help_result = CliRunner().invoke(cli_app, ["youtube-publish-package", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "--privacy" not in help_result.output
    assert "--public" not in help_result.output
    assert "--unlisted" not in help_result.output

    for flag, value in (("--privacy", "public"), ("--privacy", "unlisted")):
        rejected = CliRunner().invoke(
            cli_app,
            [
                "youtube-publish-package",
                str(package_dir),
                "--title",
                "T",
                "--description",
                "D",
                flag,
                value,
            ],
        )
        assert rejected.exit_code != 0
        assert "no such option" in rejected.output.lower()


# ---------------------------------------------------------------------------
# 26. Execute path also never constructs JobRepository/ContentEngine
# ---------------------------------------------------------------------------


def test_execute_upload_never_constructs_db_objects(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings_and_youtube(monkeypatch)
    _patch_no_db(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "T",
            "--description",
            "D",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 28. No real YouTube request in tests - canary: patch the real Google API
# client builder to explode; the fakes above never call it, so this must
# stay silent for every test in this file.
# ---------------------------------------------------------------------------


def test_canary_real_google_api_client_never_invoked(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from robin_content_engine import uploader as uploader_module
    from robin_content_engine import youtube_auth as youtube_auth_module

    def exploding_build(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("real googleapiclient.discovery.build must never be called in tests.")

    monkeypatch.setattr(uploader_module, "build", exploding_build)
    monkeypatch.setattr(youtube_auth_module, "build", exploding_build)
    _patch_settings_and_youtube(monkeypatch)
    _patch_no_db(monkeypatch)

    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "T",
            "--description",
            "D",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Channel mismatch surfaces cleanly through the CLI too
# ---------------------------------------------------------------------------


def test_execute_upload_wrong_channel_fails_via_cli(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "Settings", lambda: FakeSettings("UC_someone_else"))
    monkeypatch.setattr(cli_module, "YouTubeAuth", FakeAuth)
    monkeypatch.setattr(cli_module, "YouTubeUploader", FakeUploader)
    _patch_no_db(monkeypatch)
    FakeUploader.captured_kwargs = {}
    FakeUploader.upload_calls = []

    result = CliRunner().invoke(
        cli_app,
        [
            "youtube-publish-package",
            str(package_dir),
            "--title",
            "T",
            "--description",
            "D",
            "--execute-private-upload",
        ],
    )

    assert result.exit_code != 0
    assert "does not match" in result.output
    assert FakeUploader.upload_calls == []
    assert not (package_dir / "upload_attempt.json").exists()


def test_dry_run_does_not_modify_package_via_cli(package_dir: Path) -> None:
    manifest_before = (package_dir / "manifest.json").read_text(encoding="utf-8")

    CliRunner().invoke(
        cli_app,
        ["youtube-publish-package", str(package_dir), "--title", "T", "--description", "D"],
    )

    assert (package_dir / "manifest.json").read_text(encoding="utf-8") == manifest_before
    assert not (package_dir / "upload_attempt.json").exists()
    assert not (package_dir / "upload_receipt.json").exists()
