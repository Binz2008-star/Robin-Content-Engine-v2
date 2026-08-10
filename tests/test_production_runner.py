from __future__ import annotations

import json
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
    build_automatic_metadata,
    local_upload_state,
    production_status,
    run_production,
    run_production_once,
)
from robin_content_engine.quality_gate import QualityGateConfig  # noqa: E402
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402


class FakeRepository:
    """Only implements running()/get_job()/list_jobs()/enqueue_api_job() -
    the only calls run_production()/run_production_once()/
    production_status() are allowed to make. Any attempt to call a
    status/attempts/rights-mutating method raises AttributeError, which
    fails a test relying on it - that absence is itself the proof of
    read-only (beyond capture registration), no-job-state-mutation
    behavior."""

    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self.get_job_calls: list[int] = []
        self.list_jobs_calls = 0
        self.enqueue_calls: list[dict[str, Any]] = []

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
        status: str = "pending",
        youtube_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": source_title,
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


class OnceOnlyFakeRepository(FakeRepository):
    """Mimics the real psycopg_pool.ConnectionPool lifecycle used by
    JobRepository: the underlying pool is a single object that can be
    opened and closed exactly once - opening it again after it has been
    closed raises, exactly like the real `PoolClosed` error hit during
    the real Windows production-run-once smoke. Reentrant no-op fakes
    (plain FakeRepository) never caught that bug because their running()
    is unconditionally reentrant; this fake exists specifically to catch
    a regression back to a second repository.running() cycle within a
    single run_production_once()/run_production() call."""

    def __init__(self) -> None:
        super().__init__()
        self.running_enter_count = 0
        self._closed = False

    @contextmanager
    def running(self):
        if self._closed:
            raise RuntimeError(
                "PoolClosed: pool has already been opened/closed and cannot be reused"
            )
        self.running_enter_count += 1
        try:
            yield self
        finally:
            self._closed = True


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


def _fake_settings(work_dir: Path, capture_dir: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        work_dir=work_dir,
        capture_source_dir=capture_dir or (work_dir / "captures"),
        capture_stability_wait_seconds=0.0,
    )


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
    the audio track. with_speech=False keeps a genuine silent (anullsrc)
    audio STREAM throughout - present but with no signal, so it still
    satisfies quality_gate's audio_present check (stream existence, not
    content) while faster-whisper legitimately returns no transcribable
    speech."""
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


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_production()'s packaging step defaults to the literal relative
    "work/ready/" root (deliberately not Settings.work_dir-relative,
    matching short-package's own design) - every test must run from its
    own isolated cwd, or repeated runs (and, worse, different test
    files reusing the same small job ids) collide on the same real
    work/ready/ directory and its upload_attempt.json/upload_receipt.json
    markers. autouse so no test can forget this."""
    monkeypatch.chdir(tmp_path)


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
    FakeRecognizer.segments = [
        TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="hello there"),
        TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="general kenobi"),
    ]


@pytest.fixture
def patched_recognizer(monkeypatch: pytest.MonkeyPatch) -> type[FakeRecognizer]:
    monkeypatch.setattr(pr_module, "FasterWhisperRecognizer", FakeRecognizer)
    return FakeRecognizer


def _write_marker(
    package_dir: Path, filename: str, payload: dict[str, Any] | None = None
) -> None:
    text = json.dumps(payload or {"status": "started"})
    (package_dir / filename).write_text(text, encoding="utf-8")


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
    assert result.package.quality_gate.passed is True
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

    result = run_production(2, 1, repo, settings)

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

    assert reframe_calls["n"] == 1
    assert len(FakeRecognizer.instances) == 1

    assert second.final_video_path == first.final_video_path
    assert second.package is not None and first.package is not None
    assert second.package.package_dir == first.package.package_dir
    assert second.package.manifest == first.package.manifest


def test_run_production_second_run_reuses_and_revalidates_package(
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
    # package_short() was never called again on the second run (it would
    # have refused to overwrite and raised) - the manifest is untouched
    assert second.package.manifest_path.stat().st_mtime == manifest_mtime_before
    assert second.package.package_dir == first.package.package_dir
    # but it WAS re-validated (quality_gate re-run fresh, per the Phase 9
    # contract) rather than blindly trusted
    assert second.package.quality_gate.passed is True


# ---------------------------------------------------------------------------
# Corrupt/stale package is rejected, not blindly reused
# ---------------------------------------------------------------------------


def test_run_production_rejects_corrupt_existing_package(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=10, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(10, 1, repo, settings)
    assert first.package is not None

    # Tamper with the packaged bytes after the fact - simulates disk
    # corruption or an out-of-band edit. SHA-256 not matching the
    # manifest must be caught, not silently reused.
    with first.package.packaged_video_path.open("ab") as handle:
        handle.write(b"\x00" * 16)

    with pytest.raises(ProductionRunError, match="failed validation"):
        run_production(10, 1, repo, settings)


def test_run_production_rejects_package_with_deleted_manifest(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=11, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(11, 1, repo, settings)
    assert first.package is not None
    first.package.manifest_path.unlink()

    with pytest.raises(ProductionRunError, match="failed validation"):
        run_production(11, 1, repo, settings)


# ---------------------------------------------------------------------------
# Source file integrity
# ---------------------------------------------------------------------------


def test_run_production_does_not_modify_source(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    original_size = speech_video.stat().st_size
    original_mtime = speech_video.stat().st_mtime

    repo = FakeRepository()
    repo.seed(job_id=12, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    run_production(12, 1, repo, settings)

    assert speech_video.stat().st_size == original_size
    assert speech_video.stat().st_mtime == original_mtime


# ---------------------------------------------------------------------------
# local_upload_state()
# ---------------------------------------------------------------------------


def test_local_upload_state_none(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    assert local_upload_state(package_dir) == "none"


def test_local_upload_state_ambiguous(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    _write_marker(package_dir, "upload_attempt.json")
    assert local_upload_state(package_dir) == "ambiguous"


def test_local_upload_state_published(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    _write_marker(package_dir, "upload_receipt.json")
    assert local_upload_state(package_dir) == "published"


def test_local_upload_state_receipt_wins_over_attempt(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    _write_marker(package_dir, "upload_attempt.json")
    _write_marker(package_dir, "upload_receipt.json")
    assert local_upload_state(package_dir) == "published"


# ---------------------------------------------------------------------------
# build_automatic_metadata()
# ---------------------------------------------------------------------------


def test_build_automatic_metadata_is_deterministic_and_truthful() -> None:
    title, description = build_automatic_metadata("Fortnite 2026-08-08 16-03-14")

    assert title == "Fortnite 2026-08-08 16-03-14 — Highlight"
    assert description == (
        "Automatically processed from operator-owned gameplay by Robin Content Engine."
    )
    # deterministic: same input always yields the same output
    assert build_automatic_metadata("Fortnite 2026-08-08 16-03-14") == (title, description)


# ---------------------------------------------------------------------------
# run_production_once(): capture scan + automatic selection
# ---------------------------------------------------------------------------


def test_run_production_once_no_eligible_job(tmp_path: Path) -> None:
    repo = FakeRepository()
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.selected_job_id is None
    assert result.run is None
    assert result.capture_scan.videos_discovered == 0


def test_run_production_once_new_capture_discovered_never_auto_approved(
    speech_video: Path, tmp_path: Path
) -> None:
    import shutil

    repo = FakeRepository()
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    shutil.copy(speech_video, capture_dir / "new_capture.mp4")
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.capture_scan.new_registered == 1
    assert len(repo.enqueue_calls) == 1
    assert repo.enqueue_calls[0]["rights_confirmed"] is False
    # the newly (unconfirmed) discovered job is not eligible for automatic
    # processing - rights were never auto-approved
    assert result.selected_job_id is None


def test_run_production_once_rejected_rights_job_never_processed(tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path="/tmp/whatever.mp4", rights_confirmed=False)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.selected_job_id is None
    assert repo.get_job_calls == []


# ---------------------------------------------------------------------------
# CTO review round 2, item 1: eligibility must honor queue state, not just
# rights_confirmed - a rights-confirmed row whose DB status is anything
# other than "pending" (or that already carries a youtube_id) must never
# be selected automatically.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "excluded_status", ["uploaded", "rendered", "processing", "failed", "quarantined"]
)
def test_run_production_once_excludes_non_pending_status(
    excluded_status: str, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path="/tmp/whatever.mp4",
        rights_confirmed=True,
        status=excluded_status,
    )
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.selected_job_id is None
    assert repo.get_job_calls == []


def test_run_production_once_excludes_job_with_existing_youtube_id(
    speech_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=True,
        status="pending",
        youtube_id="MMaVyYUt8XE",
    )
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.selected_job_id is None
    assert repo.get_job_calls == []


def test_run_production_once_pending_job_with_no_youtube_id_is_selected(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=True,
        status="pending",
        youtube_id=None,
    )
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert result.selected_job_id == 1


# ---------------------------------------------------------------------------
# CTO review round 2, item 2: at most ONE job processed per invocation -
# once media processing begins for the selected candidate, a failure
# there must end the invocation, never falling through to a second
# candidate.
# ---------------------------------------------------------------------------


def test_run_production_once_qc_failure_on_candidate_one_never_tries_candidate_two(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    call_count = {"n": 0}
    original_loaded_job = pr_module._run_production_loaded_job

    def counting_loaded_job(job: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if job["id"] == 1:
            # force a QC failure for candidate 1 only, without touching
            # candidate 2's own real (passing) run
            strict_config = QualityGateConfig(min_clip_seconds=100.0, max_clip_seconds=200.0)
            kwargs["quality_gate_config"] = strict_config
        return original_loaded_job(job, *args, **kwargs)

    monkeypatch.setattr(pr_module, "_run_production_loaded_job", counting_loaded_job)

    result = run_production_once(repo, settings)

    # candidate 1 (lowest id) was selected and _run_production_loaded_job()
    # was called for it exactly once - candidate 2 was never attempted,
    # even though it is otherwise eligible and would have passed
    assert call_count["n"] == 1
    assert result.selected_job_id == 1
    assert result.run is not None
    assert result.run.job_id == 1
    assert result.run.quality_gate.passed is False
    assert result.run.package is None


def test_run_production_once_precheck_never_runs_highlight_analysis(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The precheck phase (scanning candidates for a pre-existing
    receipt/attempt) must be pure filesystem - proven here by counting
    calls to _run_highlight_analysis() and confirming it runs only once
    (for the single selected job), never once per candidate scanned."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    analysis_calls = {"n": 0}
    original_analysis = pr_module._run_highlight_analysis

    def counting_analysis(*args: Any, **kwargs: Any) -> Any:
        analysis_calls["n"] += 1
        return original_analysis(*args, **kwargs)

    monkeypatch.setattr(pr_module, "_run_highlight_analysis", counting_analysis)

    run_production_once(repo, settings)

    # exactly one call - from the single run_production() call for the
    # selected job, not from prechecking both candidates
    assert analysis_calls["n"] == 1


def test_run_production_once_selects_exactly_one_deterministic_job(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=5, source_path=str(speech_video), rights_confirmed=True)
    repo.seed(job_id=3, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    # lowest job id wins (deterministic FIFO), never both
    assert result.selected_job_id == 3
    assert result.run is not None
    assert result.run.job_id == 3


def test_run_production_once_skips_already_published_job(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    # process it once and mark it published
    first = run_production_once(repo, settings)
    assert first.selected_job_id == 1
    assert first.run is not None and first.run.package is not None
    _write_marker(first.run.package.package_dir, "upload_receipt.json")

    second = run_production_once(repo, settings)

    assert second.selected_job_id is None
    assert any(s.job_id == 1 and "published" in s.reason for s in second.skipped)


def test_run_production_once_ambiguous_job_stopped_not_reselected(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    first = run_production_once(repo, settings)
    assert first.run is not None and first.run.package is not None
    _write_marker(first.run.package.package_dir, "upload_attempt.json")

    second = run_production_once(repo, settings)

    assert second.selected_job_id is None
    assert any(s.job_id == 1 and "ambiguous" in s.reason for s in second.skipped)


def test_run_production_once_falls_through_to_second_eligible_job(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    first = run_production_once(repo, settings)
    assert first.selected_job_id == 1
    assert first.run is not None and first.run.package is not None
    _write_marker(first.run.package.package_dir, "upload_receipt.json")

    second = run_production_once(repo, settings)

    assert second.selected_job_id == 2


def test_run_production_once_no_db_mutation_beyond_capture_registration(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    run_production_once(repo, settings)

    # FakeRepository defines no status/attempts/rights-mutating method at
    # all - if run_production_once() had called one, this test would
    # already have raised AttributeError above.
    assert repo.jobs[1]["rights_confirmed"] is True


# ---------------------------------------------------------------------------
# production_status()
# ---------------------------------------------------------------------------


def test_production_status_counts_every_state(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    settings = _fake_settings(tmp_path / "work")

    # 1: awaiting rights
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=False)
    # 2: rights-approved, nothing produced yet
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    # 3: will be fully packaged (not published)
    repo.seed(job_id=3, source_path=str(speech_video), rights_confirmed=True)
    # 4: will be published
    repo.seed(job_id=4, source_path=str(speech_video), rights_confirmed=True)
    # 5: will be ambiguous
    repo.seed(job_id=5, source_path=str(speech_video), rights_confirmed=True)

    packaged = run_production(3, 1, repo, settings)
    published = run_production(4, 1, repo, settings)
    ambiguous = run_production(5, 1, repo, settings)
    assert packaged.package is not None
    assert published.package is not None
    assert ambiguous.package is not None
    _write_marker(published.package.package_dir, "upload_receipt.json")
    _write_marker(ambiguous.package.package_dir, "upload_attempt.json")

    status = production_status(repo, settings)

    assert status.awaiting_rights == 1
    assert status.rejected == 0
    assert status.rights_approved_eligible == 1
    assert status.packaged == 1
    assert status.uploaded_private == 1
    assert status.ambiguous == 1
    assert {j.job_id for j in status.jobs} == {1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# CTO review round 2, item 4: production-status truthfulness - an
# explicitly rejected/quarantined unconfirmed job must not be shown as
# "awaiting rights", using the same reviewable-state predicate
# JobRepository.list_pending_rights_review() itself uses.
# ---------------------------------------------------------------------------


def test_production_status_explicitly_rejected_job_is_not_awaiting_rights(
    speech_video: Path, tmp_path: Path
) -> None:
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=False,
        status="quarantined",
        last_error="Rights rejected by operator.",
    )
    settings = _fake_settings(tmp_path / "work")

    status = production_status(repo, settings)

    assert status.awaiting_rights == 0
    assert status.rejected == 1
    assert status.jobs[0].state == "rejected"


def test_production_status_auto_quarantined_unconfirmed_job_still_awaiting_rights(
    speech_video: Path, tmp_path: Path
) -> None:
    """An auto-quarantined-before-review job (quarantine_unconfirmed()'s
    own AUTO_QUARANTINE_REASON marker, not an operator decision) must
    still count as "awaiting rights", not "rejected" - it remains
    reviewable via rights-approve/rights-reject, exactly matching
    JobRepository.list_pending_rights_review()'s own semantics."""
    from robin_content_engine.database import AUTO_QUARANTINE_REASON

    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=False,
        status="quarantined",
        last_error=AUTO_QUARANTINE_REASON,
    )
    settings = _fake_settings(tmp_path / "work")

    status = production_status(repo, settings)

    assert status.awaiting_rights == 1
    assert status.rejected == 0
    assert status.jobs[0].state == "awaiting_rights"


def test_production_status_processing_state(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    """A job with a reframed/captioned file in work/highlights/ but no
    package yet (e.g. an interrupted run before QC/packaging) reports as
    "processing", not "rights_approved_eligible"."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    result = run_production(1, 1, repo, settings)
    assert result.package is not None
    # simulate "not yet packaged" by removing only the package directory,
    # leaving the reframed/captioned artifact behind in work/highlights/
    import shutil

    shutil.rmtree(result.package.package_dir)

    status = production_status(repo, settings)

    assert status.processing == 1
    assert status.packaged == 0


def test_production_status_is_read_only_no_mutation(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    production_status(repo, settings)

    assert repo.list_jobs_calls >= 1


# ---------------------------------------------------------------------------
# Real-smoke blocker correction: repository.running() must be entered
# exactly once per invocation, never reopened after close - reproducing
# the real psycopg_pool.ConnectionPool lifecycle (via OnceOnlyFakeRepository)
# that the plain reentrant FakeRepository never exercised, and that a real
# Windows production-run-once smoke hit as a hard `PoolClosed` crash.
# ---------------------------------------------------------------------------


def test_run_production_once_opens_repository_exactly_once(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = OnceOnlyFakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert repo.running_enter_count == 1
    assert result.selected_job_id == 1
    assert result.run is not None
    assert result.run.package is not None


def test_run_production_once_no_eligible_job_opens_repository_exactly_once(
    tmp_path: Path,
) -> None:
    """Even the empty-queue path (no candidate selected, no media
    processing) must still only open the repository once, covering both
    scan_captures() and list_jobs()."""
    repo = OnceOnlyFakeRepository()
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    result = run_production_once(repo, settings)

    assert repo.running_enter_count == 1
    assert result.selected_job_id is None


def test_run_production_manual_path_opens_repository_exactly_once(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    """The public run_production() contract (used by manual
    `production-run`) must still work unchanged, using exactly one
    repository.running() cycle - the job lookup - before delegating all
    media processing to the internal loaded-job helper."""
    repo = OnceOnlyFakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    result = run_production(1, 1, repo, settings)

    assert repo.running_enter_count == 1
    assert result.job_id == 1
    assert result.package is not None


def test_run_production_once_never_calls_public_run_production(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_production_once() must delegate directly to
    _run_production_loaded_job(), never to the public run_production() -
    calling the public function would attempt a second
    repository.running() cycle against an already-closed connection
    pool."""
    repo = OnceOnlyFakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "run_production_once() must not call the public run_production()"
        )

    monkeypatch.setattr(pr_module, "run_production", fail_if_called)

    result = run_production_once(repo, settings)

    assert result.selected_job_id == 1
    assert repo.running_enter_count == 1
    assert repo.get_job_calls == []  # never opens individual jobs
