from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402

from robin_content_engine import quality_gate as quality_gate_module  # noqa: E402
from robin_content_engine.quality_gate import (  # noqa: E402
    PackagingError,
    QualityGateConfig,
    package_short,
    run_quality_gate,
)

# Small explicit bounds so synthetic fixtures can stay short (fast to
# encode) while still exercising the real duration_within_bounds logic.
# min_width/min_height are lowered to match the small 90x160 test
# fixtures - the production default (1080x1920) is exercised by the
# dedicated below-min-resolution test.
TEST_CONFIG = QualityGateConfig(
    min_clip_seconds=2.0,
    max_clip_seconds=8.0,
    duration_tolerance_seconds=0.3,
    min_width=90,
    min_height=160,
)


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _make_simple_video(
    path: Path,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int = 24,
    with_audio: bool = True,
    color: str | None = None,
) -> Path:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video_source = (
        f"color=c={color}:s={width}x{height}:r={fps}:d={duration}"
        if color
        else f"testsrc=s={width}x{height}:r={fps}:d={duration}"
    )
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", video_source]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:r=16000:d={duration}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(path))
    _run_ffmpeg(cmd)
    return path


def _make_black_edge_video(
    path: Path, *, width: int, height: int, black_first: bool, fps: int = 24
) -> Path:
    """4s clip: 1s of black+silence and 3s of a bright test pattern+tone,
    concatenated in the requested order, so either the first or the last
    decodable frame is genuinely black."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    black_v = f"color=c=black:s={width}x{height}:r={fps}:d=1"
    black_a = "anullsrc=r=16000:cl=mono:d=1"
    bright_v = f"testsrc=s={width}x{height}:r={fps}:d=3"
    bright_a = "sine=f=440:r=16000:d=3"
    if black_first:
        v_inputs, a_inputs = [black_v, bright_v], [black_a, bright_a]
    else:
        v_inputs, a_inputs = [bright_v, black_v], [bright_a, black_a]

    cmd = [ffmpeg, "-y"]
    for src in v_inputs:
        cmd += ["-f", "lavfi", "-i", src]
    for src in a_inputs:
        cmd += ["-f", "lavfi", "-i", src]
    cmd += [
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[vout];[2:a][3:a]concat=n=2:v=0:a=1[aout]",
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    _run_ffmpeg(cmd)
    return path


@pytest.fixture(scope="module")
def valid_vertical_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4s, exact 9:16 (90x160), bright test pattern + tone - should PASS
    every check under TEST_CONFIG."""
    out = tmp_path_factory.mktemp("qgate_valid") / "valid.mp4"
    return _make_simple_video(out, width=90, height=160, duration=4.0)


@pytest.fixture(scope="module")
def landscape_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4s, 16:9 (160x90) - wrong aspect ratio, everything else valid."""
    out = tmp_path_factory.mktemp("qgate_landscape") / "landscape.mp4"
    return _make_simple_video(out, width=160, height=90, duration=4.0)


@pytest.fixture(scope="module")
def too_short_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """1s, under TEST_CONFIG's 2.0s minimum."""
    out = tmp_path_factory.mktemp("qgate_short") / "short.mp4"
    return _make_simple_video(out, width=90, height=160, duration=1.0)


@pytest.fixture(scope="module")
def no_audio_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("qgate_noaudio") / "noaudio.mp4"
    return _make_simple_video(out, width=90, height=160, duration=4.0, with_audio=False)


@pytest.fixture(scope="module")
def dark_but_valid_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4s of a very dark (but not literally black) solid fill - mean luma
    well above the conservative black-frame threshold. Must NOT be
    falsely rejected as a black start/end frame."""
    out = tmp_path_factory.mktemp("qgate_dark") / "dark.mp4"
    return _make_simple_video(out, width=90, height=160, duration=4.0, color="0x101010")


@pytest.fixture(scope="module")
def black_start_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("qgate_black_start") / "black_start.mp4"
    return _make_black_edge_video(out, width=90, height=160, black_first=True)


@pytest.fixture(scope="module")
def black_end_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("qgate_black_end") / "black_end.mp4"
    return _make_black_edge_video(out, width=90, height=160, black_first=False)


def _checks_by_name(
    result: quality_gate_module.QualityGateResult,
) -> dict[str, quality_gate_module.QualityCheck]:
    return {c.name: c for c in result.checks}


# ---------------------------------------------------------------------------
# 1. Valid 9:16 MP4 -> PASS
# ---------------------------------------------------------------------------


def test_valid_vertical_video_passes(valid_vertical_video: Path) -> None:
    result = run_quality_gate(valid_vertical_video, TEST_CONFIG)

    assert result.passed is True
    assert all(c.passed for c in result.checks)
    assert {c.name for c in result.checks} == set(quality_gate_module._ALL_CHECK_NAMES)
    assert result.media.width == 90
    assert result.media.height == 160
    assert result.media.has_audio is True


# ---------------------------------------------------------------------------
# 2. Nonexistent file -> FAIL
# ---------------------------------------------------------------------------


def test_nonexistent_file_fails(tmp_path: Path) -> None:
    result = run_quality_gate(tmp_path / "does-not-exist.mp4", TEST_CONFIG)

    assert result.passed is False
    checks = _checks_by_name(result)
    assert checks["file_exists"].passed is False
    # every other check is explicitly present and failed, never omitted
    assert len(result.checks) == len(quality_gate_module._ALL_CHECK_NAMES)
    assert all(not c.passed for c in result.checks)


# ---------------------------------------------------------------------------
# 3. Zero-byte file -> FAIL
# ---------------------------------------------------------------------------


def test_zero_byte_file_fails(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    result = run_quality_gate(empty, TEST_CONFIG)

    assert result.passed is False
    checks = _checks_by_name(result)
    assert checks["file_exists"].passed is True
    assert checks["file_non_empty"].passed is False
    assert len(result.checks) == len(quality_gate_module._ALL_CHECK_NAMES)


# ---------------------------------------------------------------------------
# 4. Corrupt / not-decodable file -> FAIL
# ---------------------------------------------------------------------------


def test_corrupt_file_fails(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a real video file" * 100)

    result = run_quality_gate(corrupt, TEST_CONFIG)

    assert result.passed is False
    checks = _checks_by_name(result)
    assert checks["file_exists"].passed is True
    assert checks["file_non_empty"].passed is True
    assert checks["video_decodable"].passed is False
    assert len(result.checks) == len(quality_gate_module._ALL_CHECK_NAMES)


# ---------------------------------------------------------------------------
# 5. Landscape video -> FAIL aspect ratio
# ---------------------------------------------------------------------------


def test_landscape_video_fails_aspect_ratio(landscape_video: Path) -> None:
    result = run_quality_gate(landscape_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["aspect_ratio_9_16"].passed is False
    assert checks["video_decodable"].passed is True
    assert checks["duration_within_bounds"].passed is True
    assert result.passed is False


# ---------------------------------------------------------------------------
# 6. Below-minimum-resolution video -> FAIL min_resolution
# ---------------------------------------------------------------------------


def test_below_min_resolution_video_fails(tmp_path: Path) -> None:
    """A tiny but otherwise-valid clip (e.g. a 200x360 crop that was never
    upscaled) must fail the gate under the production default minimum of
    1080x1920 - never uploadable as-is."""
    small = _make_simple_video(tmp_path / "small.mp4", width=90, height=160, duration=4.0)
    default_config = QualityGateConfig(min_clip_seconds=2.0, max_clip_seconds=8.0)

    result = run_quality_gate(small, default_config)

    checks = _checks_by_name(result)
    assert checks["min_resolution"].passed is False
    assert checks["video_decodable"].passed is True
    assert checks["duration_within_bounds"].passed is True
    assert result.passed is False


# ---------------------------------------------------------------------------
# 7. Invalid duration -> FAIL
# ---------------------------------------------------------------------------


def test_too_short_duration_fails(too_short_video: Path) -> None:
    result = run_quality_gate(too_short_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["duration_within_bounds"].passed is False
    assert result.passed is False


# ---------------------------------------------------------------------------
# 7. Missing audio -> FAIL
# ---------------------------------------------------------------------------


def test_missing_audio_fails(no_audio_video: Path) -> None:
    result = run_quality_gate(no_audio_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["audio_present"].passed is False
    assert result.media.has_audio is False
    assert result.passed is False


# ---------------------------------------------------------------------------
# 8 / 9. Black start / end frame -> FAIL
# ---------------------------------------------------------------------------


def test_black_start_frame_fails(black_start_video: Path) -> None:
    result = run_quality_gate(black_start_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["no_black_start_frame"].passed is False
    assert result.passed is False


def test_black_end_frame_fails(black_end_video: Path) -> None:
    result = run_quality_gate(black_end_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["no_black_end_frame"].passed is False
    assert result.passed is False


# ---------------------------------------------------------------------------
# 10. Ordinary dark-but-valid frames must NOT be falsely rejected
# ---------------------------------------------------------------------------


def test_dark_but_not_black_video_is_not_falsely_rejected(dark_but_valid_video: Path) -> None:
    result = run_quality_gate(dark_but_valid_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["no_black_start_frame"].passed is True
    assert checks["no_black_end_frame"].passed is True
    assert result.passed is True


# ---------------------------------------------------------------------------
# 11. Sampled-frame decode failure -> FAIL
# ---------------------------------------------------------------------------


def test_sampled_frame_decode_failure_fails(
    valid_vertical_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read = quality_gate_module._read_frame_at
    call_count = {"n": 0}

    def flaky_read(cap: object, frame_index: int) -> object:
        call_count["n"] += 1
        # Calls 1 and 2 are the direct start/end frame reads (must
        # succeed so the black-frame checks stay isolated from this
        # failure); the first sampled-loop read (call 3) fails.
        if call_count["n"] == 3:
            return None
        return original_read(cap, frame_index)  # type: ignore[arg-type]

    monkeypatch.setattr(quality_gate_module, "_read_frame_at", flaky_read)

    result = run_quality_gate(valid_vertical_video, TEST_CONFIG)

    checks = _checks_by_name(result)
    assert checks["sampled_frame_decode_integrity"].passed is False
    assert checks["no_black_start_frame"].passed is True
    assert checks["no_black_end_frame"].passed is True
    assert result.passed is False


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


def test_package_refuses_failed_gate(landscape_video: Path, tmp_path: Path) -> None:
    dest_root = tmp_path / "ready"

    with pytest.raises(PackagingError, match="Quality gate FAILED"):
        package_short(landscape_video, dest_root, config=TEST_CONFIG)

    assert not dest_root.exists()


def test_successful_package_creates_mp4_and_manifest(
    valid_vertical_video: Path, tmp_path: Path
) -> None:
    dest_root = tmp_path / "ready"

    result = package_short(valid_vertical_video, dest_root, config=TEST_CONFIG)

    assert result.packaged_video_path.is_file()
    assert result.packaged_video_path.stat().st_size > 0
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["quality_gate_passed"] is True
    assert manifest["original_artifact_path"] == str(valid_vertical_video)
    assert manifest["width"] == 90
    assert manifest["height"] == 160
    assert manifest["audio_present"] is True
    assert "format_version" in manifest
    assert "packaged_at" in manifest
    # no secrets/tokens of any kind in the manifest
    manifest_text = json.dumps(manifest).lower()
    for forbidden in ("token", "client_secret", "api_key", "password", "database_url"):
        assert forbidden not in manifest_text


def test_manifest_sha256_matches_packaged_bytes(
    valid_vertical_video: Path, tmp_path: Path
) -> None:
    import hashlib

    dest_root = tmp_path / "ready"

    result = package_short(valid_vertical_video, dest_root, config=TEST_CONFIG)

    actual_sha256 = hashlib.sha256(result.packaged_video_path.read_bytes()).hexdigest()
    assert result.manifest["sha256"] == actual_sha256


def test_package_refuses_overwrite(valid_vertical_video: Path, tmp_path: Path) -> None:
    dest_root = tmp_path / "ready"

    first = package_short(valid_vertical_video, dest_root, config=TEST_CONFIG)
    original_manifest_bytes = first.manifest_path.read_bytes()

    with pytest.raises(PackagingError, match="already exists"):
        package_short(valid_vertical_video, dest_root, config=TEST_CONFIG)

    assert first.manifest_path.read_bytes() == original_manifest_bytes


def test_package_does_not_modify_source(valid_vertical_video: Path, tmp_path: Path) -> None:
    original_size = valid_vertical_video.stat().st_size
    original_mtime = valid_vertical_video.stat().st_mtime

    package_short(valid_vertical_video, tmp_path / "ready", config=TEST_CONFIG)

    assert valid_vertical_video.stat().st_size == original_size
    assert valid_vertical_video.stat().st_mtime == original_mtime
