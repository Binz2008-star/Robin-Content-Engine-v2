from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402

from robin_content_engine.models import UploadResult  # noqa: E402
from robin_content_engine.publishing import (  # noqa: E402
    PublishingError,
    build_publish_metadata,
    dry_run,
    execute_private_upload,
    validate_package,
)
from robin_content_engine.quality_gate import QualityGateConfig, package_short  # noqa: E402
from robin_content_engine.youtube_auth import ChannelIdentity, YouTubeAuthError  # noqa: E402

# Small explicit bounds so synthetic fixtures stay fast, same technique as
# tests/test_quality_gate.py.
TEST_CONFIG = QualityGateConfig(
    min_clip_seconds=2.0,
    max_clip_seconds=8.0,
    duration_tolerance_seconds=0.3,
)

EXPECTED_CHANNEL_ID = "UC_expected_channel"
WRONG_CHANNEL_ID = "UC_wrong_channel"


class FakeAuth:
    def __init__(
        self, channel_id: str = EXPECTED_CHANNEL_ID, error: Exception | None = None
    ) -> None:
        self.channel_id = channel_id
        self.error = error
        self.calls = 0

    def verify_current_channel(self) -> ChannelIdentity:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ChannelIdentity(channel_id=self.channel_id, title="Test Channel", custom_url=None)


class FakeUploader:
    def __init__(self, result: UploadResult | None = None, error: Exception | None = None) -> None:
        self.result = result or UploadResult(youtube_id="abc123XYZ", privacy_status="private")
        self.error = error
        self.upload_calls: list[tuple[Path, Any]] = []

    def upload(self, video_path: Path, content: Any) -> UploadResult:
        self.upload_calls.append((video_path, content))
        if self.error is not None:
            raise self.error
        return self.result


def _fake_settings(expected_channel_id: str | None = EXPECTED_CHANNEL_ID) -> SimpleNamespace:
    return SimpleNamespace(youtube_expected_channel_id=expected_channel_id)


def _make_source_video(
    path: Path, *, duration: float = 4.0, width: int = 90, height: int = 160
) -> Path:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=s={width}x{height}:r=24:d={duration}",
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
    """A real, valid Phase 8D package: package_short() run against a
    genuine synthetic 9:16 clip, using TEST_CONFIG so it stays fast."""
    source = _make_source_video(tmp_path / "source.mp4")
    result = package_short(source, tmp_path / "ready", config=TEST_CONFIG)
    return result.package_dir


def _read_manifest(package_dir: Path) -> dict[str, Any]:
    return json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict[str, Any]) -> None:
    (package_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def test_build_publish_metadata_accepts_valid_input() -> None:
    metadata = build_publish_metadata(
        "  My   Title  ", "A description.", ["  #tag1 ", "tag2", "tag1"]
    )

    assert metadata.title == "My Title"
    assert metadata.description == "A description."
    assert metadata.tags == ["tag1", "tag2"]


def test_build_publish_metadata_rejects_empty_title() -> None:
    with pytest.raises(PublishingError, match="title"):
        build_publish_metadata("   ", "A description.", [])


def test_build_publish_metadata_rejects_empty_description() -> None:
    with pytest.raises(PublishingError, match="description"):
        build_publish_metadata("Title", "   ", [])


def test_build_publish_metadata_rejects_oversized_title() -> None:
    with pytest.raises(PublishingError, match="title"):
        build_publish_metadata("x" * 101, "A description.", [])


# ---------------------------------------------------------------------------
# 1. Valid package dry-run PASS
# ---------------------------------------------------------------------------


def test_dry_run_passes_for_valid_package(package_dir: Path) -> None:
    result = dry_run(
        package_dir,
        "A Valid Title",
        "A valid description.",
        ["tag1"],
        quality_gate_config=TEST_CONFIG,
    )

    assert result.validation.quality_gate.passed is True
    assert result.metadata.title == "A Valid Title"


# ---------------------------------------------------------------------------
# 2. Missing package -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_missing_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(PublishingError, match="does not exist"):
        validate_package(tmp_path / "no-such-package", quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 3. Missing manifest -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_missing_manifest_fails(package_dir: Path) -> None:
    (package_dir / "manifest.json").unlink()

    with pytest.raises(PublishingError, match=r"manifest\.json not found"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 4. Malformed manifest -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_malformed_manifest_json_fails(package_dir: Path) -> None:
    (package_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(PublishingError, match="not valid JSON"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


def test_validate_package_manifest_missing_required_keys_fails(package_dir: Path) -> None:
    _write_manifest(package_dir, {"sha256": "deadbeef"})

    with pytest.raises(PublishingError, match="missing required key"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 5. quality_gate_passed=false -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_quality_gate_not_passed_fails(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    manifest["quality_gate_passed"] = False
    _write_manifest(package_dir, manifest)

    with pytest.raises(PublishingError, match="quality_gate_passed"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 6. Missing packaged MP4 -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_missing_video_file_fails(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    video_name = Path(manifest["packaged_artifact_path"]).name
    (package_dir / video_name).unlink()

    with pytest.raises(PublishingError, match="not found"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 7. Manifest byte-size mismatch -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_byte_size_mismatch_fails(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    manifest["byte_size"] = manifest["byte_size"] + 1
    _write_manifest(package_dir, manifest)

    with pytest.raises(PublishingError, match="byte_size"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 8. SHA mismatch -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_sha256_mismatch_fails(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    manifest["sha256"] = "0" * 64
    _write_manifest(package_dir, manifest)

    with pytest.raises(PublishingError, match="SHA-256"):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 9. Packaged path escaping package directory -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_rejects_path_traversal(package_dir: Path, tmp_path: Path) -> None:
    decoy = tmp_path / "evil.mp4"
    decoy.write_bytes(b"not the real video - must never be picked up")

    manifest = _read_manifest(package_dir)
    manifest["packaged_artifact_path"] = "..\\..\\evil.mp4"
    _write_manifest(package_dir, manifest)

    with pytest.raises(PublishingError):
        validate_package(package_dir, quality_gate_config=TEST_CONFIG)

    # the decoy file outside the package directory was never validated as
    # the packaged artifact - proven by the fact that either the escape
    # guard rejected it, or (since only the basename is ever used) it
    # simply wasn't found inside package_dir. Either way nothing outside
    # package_dir is ever treated as valid.
    assert decoy.read_bytes() == b"not the real video - must never be picked up"


# ---------------------------------------------------------------------------
# 10. Re-run quality gate failure -> FAIL
# ---------------------------------------------------------------------------


def test_validate_package_rerun_gate_failure_even_with_passing_manifest(package_dir: Path) -> None:
    # Manifest says quality_gate_passed=true (from packaging with
    # TEST_CONFIG's lenient bounds) and SHA/size still match - but a
    # stricter config at validate-time must still catch it fresh, proving
    # the gate is genuinely re-run rather than trusted from the manifest.
    manifest = _read_manifest(package_dir)
    assert manifest["quality_gate_passed"] is True

    stricter_config = QualityGateConfig(min_clip_seconds=100.0, max_clip_seconds=200.0)

    with pytest.raises(PublishingError, match="quality gate FAILED"):
        validate_package(package_dir, quality_gate_config=stricter_config)


# ---------------------------------------------------------------------------
# 11. Invalid metadata -> FAIL
# ---------------------------------------------------------------------------


def test_dry_run_fails_on_invalid_metadata(package_dir: Path) -> None:
    with pytest.raises(PublishingError, match="title"):
        dry_run(package_dir, "", "A description.", [], quality_gate_config=TEST_CONFIG)


# ---------------------------------------------------------------------------
# 14. Execute path requires expected channel ID
# ---------------------------------------------------------------------------


def test_execute_requires_expected_channel_id(package_dir: Path) -> None:
    auth = FakeAuth()
    uploader = FakeUploader()

    with pytest.raises(PublishingError, match="youtube_expected_channel_id"):
        execute_private_upload(
            package_dir,
            "Title",
            "Description.",
            [],
            _fake_settings(expected_channel_id=None),
            auth,
            lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    assert uploader.upload_calls == []


# ---------------------------------------------------------------------------
# 15. Missing auth fails safely
# ---------------------------------------------------------------------------


def test_execute_missing_auth_fails_safely(package_dir: Path) -> None:
    auth = FakeAuth(error=YouTubeAuthError("not authenticated"))
    uploader = FakeUploader()

    with pytest.raises(PublishingError, match="youtube-auth"):
        execute_private_upload(
            package_dir,
            "Title",
            "Description.",
            [],
            _fake_settings(),
            auth,
            lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    assert uploader.upload_calls == []
    assert not (package_dir / "upload_attempt.json").exists()
    assert not (package_dir / "upload_receipt.json").exists()


# ---------------------------------------------------------------------------
# 16. Authenticated wrong channel -> FAIL before uploader
# ---------------------------------------------------------------------------


def test_execute_wrong_channel_fails_before_uploader_construction(package_dir: Path) -> None:
    auth = FakeAuth(channel_id=WRONG_CHANNEL_ID)
    factory_calls = {"n": 0}

    def exploding_factory() -> FakeUploader:
        factory_calls["n"] += 1
        raise AssertionError("uploader must never be constructed on a channel mismatch")

    with pytest.raises(PublishingError, match="does not match"):
        execute_private_upload(
            package_dir,
            "Title",
            "Description.",
            [],
            _fake_settings(),
            auth,
            exploding_factory,
            quality_gate_config=TEST_CONFIG,
        )

    assert factory_calls["n"] == 0
    assert not (package_dir / "upload_attempt.json").exists()


# ---------------------------------------------------------------------------
# 17. Correct channel invokes uploader exactly once
# ---------------------------------------------------------------------------


def test_execute_correct_channel_invokes_uploader_exactly_once(package_dir: Path) -> None:
    auth = FakeAuth(channel_id=EXPECTED_CHANNEL_ID)
    uploader = FakeUploader()
    factory_calls = {"n": 0}

    def factory() -> FakeUploader:
        factory_calls["n"] += 1
        return uploader

    result = execute_private_upload(
        package_dir,
        "Title",
        "Description.",
        [],
        _fake_settings(),
        auth,
        factory,
        quality_gate_config=TEST_CONFIG,
    )

    assert factory_calls["n"] == 1
    assert len(uploader.upload_calls) == 1
    assert result.youtube_id == "abc123XYZ"


# ---------------------------------------------------------------------------
# 20. Success creates upload_receipt.json
# ---------------------------------------------------------------------------


def test_execute_success_creates_receipt(package_dir: Path) -> None:
    auth = FakeAuth()
    uploader = FakeUploader(result=UploadResult(youtube_id="videoID123", privacy_status="private"))

    execute_private_upload(
        package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
        quality_gate_config=TEST_CONFIG,
    )

    receipt_path = package_dir / "upload_receipt.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["youtube_video_id"] == "videoID123"
    assert receipt["channel_id"] == EXPECTED_CHANNEL_ID
    assert receipt["privacy_status"] == "private"
    assert "uploaded_at" in receipt
    assert "format_version" in receipt
    # attempt marker is removed on success
    assert not (package_dir / "upload_attempt.json").exists()


# ---------------------------------------------------------------------------
# 21. Existing receipt blocks duplicate attempt
# ---------------------------------------------------------------------------


def test_execute_refuses_when_receipt_already_exists(package_dir: Path) -> None:
    (package_dir / "upload_receipt.json").write_text("{}", encoding="utf-8")
    auth = FakeAuth()
    uploader = FakeUploader()

    with pytest.raises(PublishingError, match="receipt already exists"):
        execute_private_upload(
            package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    assert uploader.upload_calls == []


# ---------------------------------------------------------------------------
# 22. Existing attempt marker blocks duplicate attempt
# ---------------------------------------------------------------------------


def test_execute_refuses_when_attempt_marker_already_exists(package_dir: Path) -> None:
    (package_dir / "upload_attempt.json").write_text("{}", encoding="utf-8")
    auth = FakeAuth()
    uploader = FakeUploader()

    with pytest.raises(PublishingError, match="attempt marker already exists"):
        execute_private_upload(
            package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    assert uploader.upload_calls == []


# ---------------------------------------------------------------------------
# 23. Ambiguous uploader exception preserves attempt state
# ---------------------------------------------------------------------------


def test_execute_ambiguous_failure_preserves_attempt_marker(package_dir: Path) -> None:
    auth = FakeAuth()
    uploader = FakeUploader(error=RuntimeError("connection reset after chunk 7"))

    with pytest.raises(PublishingError, match="attempt marker"):
        execute_private_upload(
            package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    attempt_path = package_dir / "upload_attempt.json"
    assert attempt_path.is_file()
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["status"] == "started"
    assert not (package_dir / "upload_receipt.json").exists()

    # a second attempt must also be refused - no automatic retry
    with pytest.raises(PublishingError, match="attempt marker already exists"):
        execute_private_upload(
            package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )


# ---------------------------------------------------------------------------
# 24 / 25. Source packaged MP4 and manifest unchanged
# ---------------------------------------------------------------------------


def test_dry_run_does_not_modify_package(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    video_name = Path(manifest["packaged_artifact_path"]).name
    video_path = package_dir / video_name
    original_bytes = video_path.read_bytes()
    original_manifest_text = (package_dir / "manifest.json").read_text(encoding="utf-8")

    dry_run(package_dir, "Title", "Description.", [], quality_gate_config=TEST_CONFIG)

    assert video_path.read_bytes() == original_bytes
    assert (package_dir / "manifest.json").read_text(encoding="utf-8") == original_manifest_text


def test_execute_success_does_not_modify_video_or_manifest(package_dir: Path) -> None:
    manifest = _read_manifest(package_dir)
    video_name = Path(manifest["packaged_artifact_path"]).name
    video_path = package_dir / video_name
    original_bytes = video_path.read_bytes()
    original_manifest_text = (package_dir / "manifest.json").read_text(encoding="utf-8")

    auth = FakeAuth()
    uploader = FakeUploader()
    execute_private_upload(
        package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
        quality_gate_config=TEST_CONFIG,
    )

    assert video_path.read_bytes() == original_bytes
    assert (package_dir / "manifest.json").read_text(encoding="utf-8") == original_manifest_text


# ---------------------------------------------------------------------------
# 27. No secrets/tokens written to attempt/receipt
# ---------------------------------------------------------------------------


def test_attempt_and_receipt_contain_no_secrets(package_dir: Path) -> None:
    auth = FakeAuth()
    uploader = FakeUploader()

    execute_private_upload(
        package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
        quality_gate_config=TEST_CONFIG,
    )

    receipt_text = (package_dir / "upload_receipt.json").read_text(encoding="utf-8").lower()
    for forbidden in ("token", "client_secret", "password", "refresh_token", "access_token"):
        assert forbidden not in receipt_text


def test_attempt_marker_contains_no_secrets_on_failure(package_dir: Path) -> None:
    auth = FakeAuth()
    uploader = FakeUploader(error=RuntimeError("boom"))

    with pytest.raises(PublishingError):
        execute_private_upload(
            package_dir, "Title", "Description.", [], _fake_settings(), auth, lambda: uploader,
            quality_gate_config=TEST_CONFIG,
        )

    attempt_text = (package_dir / "upload_attempt.json").read_text(encoding="utf-8").lower()
    for forbidden in ("token", "client_secret", "password", "refresh_token", "access_token"):
        assert forbidden not in attempt_text
