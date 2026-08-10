from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import imageio_ffmpeg  # noqa: E402
import pytest  # noqa: E402

from robin_content_engine import production_runner as pr_module  # noqa: E402
from robin_content_engine.production_runner import (  # noqa: E402
    ProductionRunError,
    run_production,
)
from robin_content_engine.quality_gate import QualityGateConfig  # noqa: E402
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402


class FakeRepository:
    """Only implements `running()` and `get_job()` - the only two calls
    run_production() is allowed to make. Any attempt to call a mutating
    method (approve_rights, claim_job, mark_*, ...) raises AttributeError,
    which fails a test relying on it - that absence is itself the proof
    of read-only, no-job-state-mutation behavior."""

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


class FakeRecognizer:
    """Stands in for FasterWhisperRecognizer - never touches faster-whisper
    or the network. transcribe_calls tracks invocation count for
    resumability assertions."""

    instances: ClassVar[list[FakeRecognizer]] = []
    segments: ClassVar[list[TranscriptSegment]] = [
        TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there"),
        TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="general kenobi"),
    ]

    def __init__(self, *, model_size: str = "base", **_kwargs: Any) -> None:
        self.model_size = model_size
        self.transcribe_calls: list[Path] = []
        FakeRecognizer.instances.append(self)

    def transcribe(self, media_path: Path) -> list[TranscriptSegment]:
        self.transcribe_calls.append(media_path)
        return list(FakeRecognizer.segments)


def _fake_settings(work_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(work_dir=work_dir)


def _make_video(
    path: Path,
    *,
    with_speech: bool,
    width: int = 128,
    height: int = 64,
) -> Path:
    """~20s synthetic wide clip: a single continuous bright moving test
    pattern for the FULL duration (never black anywhere - any valid
    highlight candidate of the default 15s+ minimum necessarily spans
    most of a 20s clip, so the video itself must never go black or the
    reframed output would legitimately fail quality_gate's black-frame
    checks) with 10s of silence then 10s of (optionally) a 440Hz tone as
    the audio track, giving highlight scoring a real audio-activity
    signal to peak on without needing any visual scene cut. with_speech=
    False keeps a genuine silent (anullsrc) audio STREAM throughout -
    present but with no signal, so it still satisfies quality_gate's
    audio_present check (stream existence, not content) while faster-
    whisper legitimately returns no transcribable speech."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    second_audio_src = "sine=f=440:r=16000:d=10" if with_speech else "anullsrc=r=16000:cl=mono:d=10"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=s={width}x{height}:r=10:d=20",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono:d=10",
        "-f",
        "lavfi",
        "-i",
        second_audio_src,
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
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture(scope="module")
def speech_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("prod_runner_speech") / "speech.mp4"
    return _make_video(out, with_speech=True)


@pytest.fixture(scope="module")
def silent_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("prod_runner_silent") / "silent.mp4"
    return _make_video(out, with_speech=False)


@pytest.fixture(autouse=True)
def _reset_fake_recognizer_instances() -> None:
    FakeRecognizer.instances.clear()


@pytest.fixture
def patched_recognizer(monkeypatch: pytest.MonkeyPatch) -> type[FakeRecognizer]:
    monkeypatch.setattr(pr_module, "FasterWhisperRecognizer", FakeRecognizer)
    return FakeRecognizer


# ---------------------------------------------------------------------------
# Happy path: speech present
# ---------------------------------------------------------------------------


def test_run_production_happy_path_with_captions(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    result = run_production(1, 1, repo, settings)

    assert result.has_captions is True
    assert result.caption_segment_count == 2
    assert result.final_video_path.name.endswith("-vertical-captioned.mp4")
    assert result.final_video_path.is_file()
    assert result.quality_gate.passed is True
    assert result.package is not None
    assert result.package.package_dir.is_dir()
    assert result.package.manifest["quality_gate_passed"] is True
    assert repo.get_job_calls == [1]


# ---------------------------------------------------------------------------
# No-speech fallback
# ---------------------------------------------------------------------------


def test_run_production_no_speech_falls_back_to_uncaptioned(
    silent_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    FakeRecognizer.segments = []  # no transcript segments at all
    repo = FakeRepository()
    repo.seed(job_id=2, source_path=str(silent_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    try:
        result = run_production(2, 1, repo, settings)
    finally:
        FakeRecognizer.segments = [
            TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there"),
            TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="general kenobi"),
        ]

    assert result.has_captions is False
    assert result.caption_segment_count == 0
    assert result.final_video_path.name.endswith("-vertical.mp4")
    assert not result.final_video_path.name.endswith("-vertical-captioned.mp4")
    assert result.final_video_path.is_file()
    # a silent-but-present audio stream still satisfies quality_gate's
    # audio_present check (stream existence, not content)
    assert result.quality_gate.passed is True
    assert result.package is not None


# ---------------------------------------------------------------------------
# Rejections (no video processing should even start)
# ---------------------------------------------------------------------------


def test_run_production_job_not_found(tmp_path: Path) -> None:
    repo = FakeRepository()
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="not found"):
        run_production(999, 1, repo, settings)


def test_run_production_rejects_unconfirmed_rights(tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=3, source_path="/tmp/whatever.mp4", rights_confirmed=False)
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="rights"):
        run_production(3, 1, repo, settings)


def test_run_production_rejects_missing_source_file(tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=4, source_path=str(tmp_path / "gone.mp4"), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="does not exist"):
        run_production(4, 1, repo, settings)


def test_run_production_rejects_zero_rank(tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=5, source_path="/tmp/whatever.mp4", rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="rank"):
        run_production(5, 0, repo, settings)

    assert repo.get_job_calls == []


def test_run_production_rejects_rank_out_of_range(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=6, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="out of range"):
        run_production(6, 999, repo, settings)


# ---------------------------------------------------------------------------
# QC failure is a soft outcome, not an exception
# ---------------------------------------------------------------------------


def test_run_production_quality_gate_failure_yields_no_package(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=7, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")
    # A config whose bounds the real produced clip cannot satisfy - forces
    # a genuine, deterministic QC failure rather than an exception.
    strict_config = QualityGateConfig(min_clip_seconds=100.0, max_clip_seconds=200.0)

    result = run_production(7, 1, repo, settings, quality_gate_config=strict_config)

    assert result.quality_gate.passed is False
    assert result.package is None


# ---------------------------------------------------------------------------
# Resumability: expensive stages are skipped on a second run
# ---------------------------------------------------------------------------


def test_run_production_second_run_reuses_reframe_and_caption(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    reframe_calls = {"n": 0}
    original_reframe = pr_module.reframe_to_vertical

    def counting_reframe(*args: Any, **kwargs: Any) -> Any:
        reframe_calls["n"] += 1
        return original_reframe(*args, **kwargs)

    pr_module.reframe_to_vertical = counting_reframe  # type: ignore[assignment]
    try:
        repo = FakeRepository()
        repo.seed(job_id=8, source_path=str(speech_video), rights_confirmed=True)
        settings = _fake_settings(tmp_path / "work")

        first = run_production(8, 1, repo, settings)
        assert reframe_calls["n"] == 1
        assert len(FakeRecognizer.instances) == 1
        assert len(FakeRecognizer.instances[0].transcribe_calls) == 1

        second = run_production(8, 1, repo, settings)
    finally:
        pr_module.reframe_to_vertical = original_reframe  # type: ignore[assignment]

    # neither the reframe nor a new recognizer/transcription happened again
    assert reframe_calls["n"] == 1
    assert len(FakeRecognizer.instances) == 1

    assert second.final_video_path == first.final_video_path
    assert second.package is not None and first.package is not None
    assert second.package.package_dir == first.package.package_dir
    assert second.package.manifest == first.package.manifest


def test_run_production_second_run_reuses_package(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=9, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(9, 1, repo, settings)
    assert first.package is not None
    manifest_mtime_before = first.package.manifest_path.stat().st_mtime

    second = run_production(9, 1, repo, settings)

    assert second.package is not None
    # package was not recreated - same manifest, same mtime (package_short
    # was never called again, since it would have refused an overwrite
    # and raised had it been attempted against an existing directory)
    assert second.package.manifest_path.stat().st_mtime == manifest_mtime_before
    assert second.package.package_dir == first.package.package_dir


# ---------------------------------------------------------------------------
# Source file integrity
# ---------------------------------------------------------------------------


def test_run_production_does_not_modify_source(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    original_size = speech_video.stat().st_size
    original_mtime = speech_video.stat().st_mtime

    repo = FakeRepository()
    repo.seed(job_id=10, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    run_production(10, 1, repo, settings)

    assert speech_video.stat().st_size == original_size
    assert speech_video.stat().st_mtime == original_mtime
