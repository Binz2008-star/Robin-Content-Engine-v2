from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
    reconcile_ambiguous_uploads,
    run_production,
    run_production_once,
)
from robin_content_engine.quality_gate import QualityGateConfig  # noqa: E402
from robin_content_engine.scene_detector import SceneDetectionError  # noqa: E402
from robin_content_engine.transcription import TranscriptSegment  # noqa: E402
from robin_content_engine.vertical_reframe import VerticalReframeError  # noqa: E402
from robin_content_engine.youtube_sync import (  # noqa: E402
    YouTubeChannelSnapshot,
    YouTubeSyncSnapshot,
    YouTubeVideoSnapshot,
)


class FakeRepository:
    """Only implements running()/get_job()/list_jobs()/enqueue_api_job()
    plus mark_deterministic_failure() - the only calls
    run_production()/run_production_once()/production_status() are
    allowed to make. Any attempt to call any other status/attempts/
    rights-mutating method raises AttributeError, which fails a test
    relying on it - that absence is itself the proof of read-only
    (beyond capture registration and deterministic-failure quarantine),
    no-job-state-mutation behavior."""

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
        """Mirrors the real JobRepository behavior tests rely on: the job
        is quarantined so a later invocation no longer selects it."""
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
# Corrupt/stale package is rebuilt, not blindly reused (and never reused
# at all when an upload marker protects it)
# ---------------------------------------------------------------------------


def test_run_production_rebuilds_corrupt_existing_package(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=10, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(10, 1, repo, settings)
    assert first.package is not None
    original_size = first.package.manifest["byte_size"]

    # Tamper with the packaged bytes after the fact - simulates disk
    # corruption or an out-of-band edit. SHA-256 not matching the
    # manifest must NOT be silently reused.
    with first.package.packaged_video_path.open("ab") as handle:
        handle.write(b"\x00" * 16)
    tampered_size = first.package.packaged_video_path.stat().st_size
    assert tampered_size == original_size + 16

    second = run_production(10, 1, repo, settings)

    # the corrupt package was deleted and rebuilt from the fresh
    # artifact - the tampered bytes are gone, so the package revalidates
    # and matches the original byte size
    assert second.package is not None
    assert second.package.package_dir == first.package.package_dir
    assert second.package.manifest["byte_size"] == original_size
    assert second.package.packaged_video_path.stat().st_size == original_size


def test_run_production_rebuilds_package_with_deleted_manifest(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=11, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(11, 1, repo, settings)
    assert first.package is not None
    first.package.manifest_path.unlink()

    second = run_production(11, 1, repo, settings)

    assert second.package is not None
    assert second.package.manifest_path.is_file()
    assert second.package.package_dir == first.package.package_dir
    assert second.package.manifest["quality_gate_passed"] is True


def test_run_production_refuses_rebuild_of_package_with_upload_attempt_marker(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    """A package that failed validation but carries an upload marker is
    protected local state - rebuilding (or reusing) it must be refused,
    not silently attempted."""
    repo = FakeRepository()
    repo.seed(job_id=13, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(13, 1, repo, settings)
    assert first.package is not None
    _write_marker(first.package.package_dir, "upload_attempt.json")
    with first.package.packaged_video_path.open("ab") as handle:
        handle.write(b"\x00" * 16)

    with pytest.raises(ProductionRunError, match="upload marker"):
        run_production(13, 1, repo, settings)


def test_run_production_refuses_rebuild_of_package_with_receipt_marker(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=14, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(14, 1, repo, settings)
    assert first.package is not None
    _write_marker(first.package.package_dir, "upload_receipt.json")
    with first.package.packaged_video_path.open("ab") as handle:
        handle.write(b"\x00" * 16)

    with pytest.raises(ProductionRunError, match="upload marker"):
        run_production(14, 1, repo, settings)


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
# reconcile_ambiguous_uploads(): ambiguous -> published via the channel's
# own private-upload inventory
# ---------------------------------------------------------------------------


def _channel_snapshot() -> YouTubeChannelSnapshot:
    return YouTubeChannelSnapshot(
        channel_id="UC_x",
        title="Test Channel",
        custom_url=None,
        description="",
        published_at=None,
        uploads_playlist_id="UU_x",
        view_count=None,
        subscriber_count=None,
        hidden_subscriber_count=False,
        video_count=None,
    )


def _video(
    video_id: str, *, published_at: datetime, privacy_status: str = "private"
) -> YouTubeVideoSnapshot:
    return YouTubeVideoSnapshot(
        video_id=video_id,
        channel_id="UC_x",
        title="clip — Highlight",
        description="",
        published_at=published_at,
        duration_seconds=58,
        privacy_status=privacy_status,
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


class FakeSync:
    def __init__(self, videos: list[YouTubeVideoSnapshot]) -> None:
        self.videos = videos
        self.fetch_count = 0

    def fetch_snapshot(self) -> YouTubeSyncSnapshot:
        self.fetch_count += 1
        return YouTubeSyncSnapshot(
            channel=_channel_snapshot(),
            videos=tuple(self.videos),
            discovered_video_count=len(self.videos),
        )


def _attempt_marker_payload(*, started_at: datetime, sha: str = "sha256-abc") -> dict[str, Any]:
    return {
        "format_version": 1,
        "package_sha256": sha,
        "expected_channel_id": "UC_x",
        "authenticated_channel_id": "UC_x",
        "started_at": started_at.isoformat(),
        "intended_privacy": "private",
        "status": "started",
    }


def _ambiguous_package(tmp_path: Path, name: str, started_at: datetime) -> Path:
    package_dir = tmp_path / name
    package_dir.mkdir()
    _write_marker(
        package_dir,
        "upload_attempt.json",
        _attempt_marker_payload(started_at=started_at),
    )
    return package_dir


def test_reconcile_no_ambiguous_packages_is_noop(tmp_path: Path) -> None:
    sync = FakeSync([])
    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert outcomes == []
    assert sync.fetch_count == 0  # never touches YouTube when nothing to resolve


def test_reconcile_resolves_single_matching_private_upload(tmp_path: Path) -> None:
    started = datetime.now(UTC) - timedelta(minutes=2)
    package_dir = _ambiguous_package(tmp_path, "job-1-highlight-01-10.0-25.0", started)
    published = started + timedelta(seconds=10)
    sync = FakeSync([_video("videoID123", published_at=published)])

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.resolved is True
    assert outcome.match_count == 1
    assert "videoID123" in outcome.detail
    # the receipt was written exactly as a confirmed upload's would be,
    # and the attempt marker removed - the package is now "published"
    assert local_upload_state(package_dir) == "published"
    assert not (package_dir / "upload_attempt.json").exists()
    receipt = json.loads((package_dir / "upload_receipt.json").read_text(encoding="utf-8"))
    assert receipt["package_sha256"] == "sha256-abc"
    assert receipt["youtube_video_id"] == "videoID123"
    assert receipt["channel_id"] == "UC_x"
    assert receipt["privacy_status"] == "private"
    assert receipt["uploaded_at"] == published.isoformat()


def test_reconcile_no_matching_upload_remains_unresolved(tmp_path: Path) -> None:
    started = datetime.now(UTC) - timedelta(hours=5)
    package_dir = _ambiguous_package(tmp_path, "pkg", started)
    # an upload exists, but hours away from the attempt's started_at
    sync = FakeSync([_video("otherVideo", published_at=datetime.now(UTC))])

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    assert outcomes[0].resolved is False
    assert outcomes[0].match_count == 0
    assert "not resolvable" in outcomes[0].detail
    # nothing was written, the marker is preserved
    assert local_upload_state(package_dir) == "ambiguous"
    assert (package_dir / "upload_attempt.json").is_file()
    assert not (package_dir / "upload_receipt.json").exists()


def test_reconcile_multiple_matches_never_guess(tmp_path: Path) -> None:
    started = datetime.now(UTC) - timedelta(minutes=1)
    package_dir = _ambiguous_package(tmp_path, "pkg", started)
    sync = FakeSync(
        [
            _video("videoA", published_at=started),
            _video("videoB", published_at=started + timedelta(seconds=5)),
        ]
    )

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    assert outcomes[0].resolved is False
    assert outcomes[0].match_count == 2
    assert "not resolvable" in outcomes[0].detail
    assert local_upload_state(package_dir) == "ambiguous"


def test_reconcile_ignores_non_private_uploads(tmp_path: Path) -> None:
    """A public/unlisted upload in the time window is NOT evidence the
    package's intended PRIVATE upload happened."""
    started = datetime.now(UTC) - timedelta(minutes=1)
    package_dir = _ambiguous_package(tmp_path, "pkg", started)
    sync = FakeSync([_video("publicVideo", published_at=started, privacy_status="public")])

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    assert outcomes[0].resolved is False
    assert outcomes[0].match_count == 0
    assert local_upload_state(package_dir) == "ambiguous"


def test_reconcile_malformed_attempt_marker_is_reported_not_guessed(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "upload_attempt.json").write_text("{ not json", encoding="utf-8")
    sync = FakeSync([_video("videoID123", published_at=datetime.now(UTC))])

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    assert outcomes[0].resolved is False
    assert "malformed" in outcomes[0].detail
    assert local_upload_state(package_dir) == "ambiguous"


def test_reconcile_naive_timestamps_are_treated_as_utc(tmp_path: Path) -> None:
    started = datetime.now(UTC) - timedelta(minutes=1)
    _ambiguous_package(tmp_path, "pkg", started)
    # naive published_at (no tz) must be interpreted as UTC, not crash
    sync = FakeSync([_video("videoID123", published_at=started.replace(tzinfo=None))])

    outcomes = reconcile_ambiguous_uploads(sync, package_dest_root=tmp_path)

    assert len(outcomes) == 1
    assert outcomes[0].resolved is True


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
    # the QC failure is a deterministic outcome: the job was quarantined
    # so the queue is not blocked by it on the next invocation
    assert result.terminal_failure is not None
    assert result.terminal_failure.job_id == 1
    assert "quality gate" in result.terminal_failure.reason.lower()
    assert repo.terminal_failures == [(1, result.terminal_failure.reason)]


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

    result = run_production_once(repo, settings)

    # FakeRepository defines no status/attempts/rights-mutating method at
    # all (except the deterministic-failure quarantine itself) - if
    # run_production_once() had called one, this test would already have
    # raised AttributeError above. On the SUCCESS path even the quarantine
    # is never called.
    assert repo.jobs[1]["rights_confirmed"] is True
    assert repo.terminal_failures == []
    assert result.terminal_failure is None


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
    # 6: rights confirmed but the row is not auto-eligible (rendered)
    repo.seed(job_id=6, source_path=str(speech_video), rights_confirmed=True, status="rendered")

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
    assert status.inactive == 1
    assert {j.job_id for j in status.jobs} == {1, 2, 3, 4, 5, 6}


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


def test_production_status_operator_quarantined_confirmed_job_is_inactive(
    speech_video: Path, tmp_path: Path
) -> None:
    """A rights-confirmed job quarantined by an operator (e.g. a source
    that can never produce a valid highlight) must NOT be reported as
    "rights_approved_eligible" - it is out of the pipeline and would never
    be auto-selected (run_production_once() requires status == "pending"),
    so the status report must not promise it is eligible. Nor is it
    "rejected" - its rights were never rejected; it is inactive until an
    operator deliberately restores it."""
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=True,
        status="quarantined",
        last_error="Quarantined by operator.",
    )
    settings = _fake_settings(tmp_path / "work")

    status = production_status(repo, settings)

    assert status.rights_approved_eligible == 0
    assert status.rejected == 0
    assert status.inactive == 1
    assert status.jobs[0].state == "inactive"


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


# ---------------------------------------------------------------------------
# Deterministic-failure quarantine (run_production_once)
# ---------------------------------------------------------------------------


def test_run_production_once_deterministic_failure_quarantines_job(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deterministic analysis failure must be quarantined (never
    retried, never blocking the queue), reported as a TerminalFailure,
    and never fall through to another candidate."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    def failing_analysis(*args: Any, **kwargs: Any) -> Any:
        raise SceneDetectionError("cannot open this video at all")

    monkeypatch.setattr(pr_module, "detect_scenes", failing_analysis)

    result = run_production_once(repo, settings)

    assert result.selected_job_id == 1
    assert result.run is None
    assert result.terminal_failure is not None
    assert result.terminal_failure.job_id == 1
    assert "cannot open this video at all" in result.terminal_failure.reason
    assert repo.terminal_failures == [(1, result.terminal_failure.reason)]
    assert repo.jobs[1]["status"] == "quarantined"


def test_run_production_once_deterministic_failure_then_next_invocation_takes_next_job(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
) -> None:
    """After a deterministic failure quarantines job 1 (missing source
    file - cannot ever succeed), the NEXT invocation must select the
    next eligible job instead of being blocked on job 1 forever."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(tmp_path / "gone.mp4"), rights_confirmed=True)
    repo.seed(job_id=2, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    first = run_production_once(repo, settings)

    assert first.selected_job_id == 1
    assert first.run is None
    assert first.terminal_failure is not None
    assert "does not exist" in first.terminal_failure.reason
    assert repo.jobs[1]["status"] == "quarantined"

    second = run_production_once(repo, settings)

    assert second.selected_job_id == 2
    assert second.run is not None
    assert second.run.job_id == 2
    assert second.terminal_failure is None
    assert repo.terminal_failures == [(1, first.terminal_failure.reason)]


def test_run_production_once_retryable_failure_propagates_without_quarantine(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient (retryable) failure - e.g. ffmpeg failing to reframe -
    must propagate to the caller for the scheduled task's logs and be
    retried on the next invocation: the job is NOT quarantined."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)

    def failing_reframe(*args: Any, **kwargs: Any) -> Any:
        raise VerticalReframeError("ffmpeg crashed mid-reframe")

    monkeypatch.setattr(pr_module, "reframe_to_vertical", failing_reframe)

    with pytest.raises(ProductionRunError) as exc_info:
        run_production_once(repo, settings)

    assert exc_info.value.retryable is True
    assert repo.terminal_failures == []
    assert repo.jobs[1]["status"] == "pending"  # untouched, retried next time


# ---------------------------------------------------------------------------
# Duplicate-upload guard on the manual entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "youtube_id,status",
    [(None, "uploaded"), ("MMaVyYUt8XE", "pending"), ("MMaVyYUt8XE", "uploaded")],
)
def test_run_production_manual_path_refuses_already_uploaded_job(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    youtube_id: str | None,
    status: str,
) -> None:
    """The authoritative duplicate-upload backstop: run_production() (the
    manual path, whose caller does not go through the automatic
    candidate filter) must refuse a job whose row says it was already
    uploaded - deterministically, so a retry could never succeed."""
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=True,
        status=status,
        youtube_id=youtube_id,
    )
    settings = _fake_settings(tmp_path / "work")

    with pytest.raises(ProductionRunError, match="already been uploaded") as exc_info:
        run_production(1, 1, repo, settings)

    assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# Highlight-analysis cache (resumability of the expensive stages)
# ---------------------------------------------------------------------------


def _count_analysis_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    counts = {
        "detect_scenes": 0,
        "extract_audio_activity": 0,
        "extract_motion_activity": 0,
        "compute_scene_density": 0,
    }
    for name in counts:
        original = getattr(pr_module, name)

        def counting(
            *args: Any,
            _name: str = name,
            _original: Any = original,
            **kwargs: Any,
        ) -> Any:
            counts[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(pr_module, name, counting)
    return counts


def test_run_production_once_analysis_cache_skips_expensive_stages_on_resume(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)
    counts = _count_analysis_calls(monkeypatch)

    first = run_production_once(repo, settings)

    assert first.selected_job_id == 1
    assert first.run is not None
    assert counts == {
        "detect_scenes": 1,
        "extract_audio_activity": 1,
        "extract_motion_activity": 1,
        "compute_scene_density": 1,
    }
    cache_path = tmp_path / "work" / "analysis" / "job-1-analysis.json"
    assert cache_path.is_file()

    second = run_production_once(repo, settings)

    assert second.selected_job_id == 1
    assert second.run is not None
    # the second run hit the cache: no scene detection, no audio/motion
    # extraction, no scene-density recomputation - the SAME deterministic
    # selection code ran over the cached signals
    assert counts == {
        "detect_scenes": 1,
        "extract_audio_activity": 1,
        "extract_motion_activity": 1,
        "compute_scene_density": 1,
    }


def test_run_production_once_analysis_cache_invalidated_on_source_change(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)
    counts = _count_analysis_calls(monkeypatch)

    first = run_production_once(repo, settings)
    assert first.run is not None
    assert counts["detect_scenes"] == 1

    # the source changed (out-of-band edit) - the cache is keyed on the
    # source's identity (path + size + mtime) and must be treated as a
    # miss, recomputing everything
    st = speech_video.stat()
    os.utime(speech_video, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

    second = run_production_once(repo, settings)

    assert second.selected_job_id == 1
    assert second.run is not None
    assert counts == {
        "detect_scenes": 2,
        "extract_audio_activity": 2,
        "extract_motion_activity": 2,
        "compute_scene_density": 2,
    }


def test_run_production_once_analysis_cache_malformed_is_a_miss(
    speech_video: Path,
    tmp_path: Path,
    patched_recognizer: type[FakeRecognizer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    settings = _fake_settings(tmp_path / "work", capture_dir)
    counts = _count_analysis_calls(monkeypatch)

    first = run_production_once(repo, settings)
    assert first.run is not None
    cache_path = tmp_path / "work" / "analysis" / "job-1-analysis.json"
    assert cache_path.is_file()

    # a partially-written (or otherwise malformed) cache must never be
    # trusted - correctness never depends on the cache
    cache_path.write_text("{ not valid json", encoding="utf-8")

    second = run_production_once(repo, settings)

    assert second.run is not None
    assert counts == {
        "detect_scenes": 2,
        "extract_audio_activity": 2,
        "extract_motion_activity": 2,
        "compute_scene_density": 2,
    }


# ---------------------------------------------------------------------------
# Caption-segment-count sidecar: truthful resume accounting
# ---------------------------------------------------------------------------


def test_run_production_caption_segment_count_restored_from_sidecar_on_resume(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(1, 1, repo, settings)
    assert first.has_captions is True
    assert first.caption_segment_count == 2
    sidecar = first.final_video_path.with_suffix(".segments.json")
    assert sidecar.is_file()

    second = run_production(1, 1, repo, settings)

    # the captioned artifact was reused, and its caption segment count
    # was restored from the durable sidecar - not re-derived, not None
    assert second.has_captions is True
    assert second.caption_segment_count == 2


def test_run_production_caption_sidecar_missing_yields_honest_none(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(1, 1, repo, settings)
    assert first.caption_segment_count == 2
    sidecar = first.final_video_path.with_suffix(".segments.json")
    sidecar.unlink()

    second = run_production(1, 1, repo, settings)

    # a resumed captioned artifact WITHOUT its sidecar reports None - an
    # honest "unknown", never a guessed number
    assert second.caption_segment_count is None
    assert len(FakeRecognizer.instances) == 1  # captioned artifact reused


def test_run_production_caption_sidecar_malformed_yields_honest_none(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(1, 1, repo, settings)
    sidecar = first.final_video_path.with_suffix(".segments.json")
    sidecar.write_text("{ broken", encoding="utf-8")

    second = run_production(1, 1, repo, settings)

    assert second.caption_segment_count is None


def test_run_production_corrupt_captioned_artifact_is_rebuilt_not_reused(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True)
    settings = _fake_settings(tmp_path / "work")

    first = run_production(1, 1, repo, settings)
    assert first.caption_segment_count == 2

    # tamper with the captioned artifact - truncate it so the quality
    # gate (which re-probes duration/size) fails and the stale artifact
    # is deleted and rebuilt, never silently reused
    with first.final_video_path.open("r+b") as handle:
        handle.truncate(first.final_video_path.stat().st_size // 2)

    second = run_production(1, 1, repo, settings)

    assert second.has_captions is True
    assert second.caption_segment_count == 2
    assert second.final_video_path == first.final_video_path
    # rebuilt: the recognizer ran again for the fresh transcription
    assert len(FakeRecognizer.instances) == 2
    assert len(FakeRecognizer.instances[1].transcribe_calls) == 1
    # the rebuilt artifact's sidecar was durably rewritten
    assert second.final_video_path.with_suffix(".segments.json").is_file()


# ---------------------------------------------------------------------------
# build_automatic_metadata(): 100-character title bound
# ---------------------------------------------------------------------------


def _title_of_length(n: int, char: str = "a") -> str:
    return char * n


def test_build_automatic_metadata_no_truncation_at_100_chars() -> None:
    source = _title_of_length(88)  # 88 + 12 = 100 exactly
    title, _ = build_automatic_metadata(source)

    assert title == f"{source} — Highlight"
    assert len(title) == 100


def test_build_automatic_metadata_truncates_beyond_100_chars() -> None:
    source = _title_of_length(89)  # 89 + 12 = 101 > 100
    title, _ = build_automatic_metadata(source)

    assert len(title) == 100
    assert title.endswith(" — Highlight")
    assert "..." in title
    assert title.startswith("a" * 85)
    # deterministic for the same input
    assert build_automatic_metadata(source)[0] == title


def test_build_automatic_metadata_truncation_strips_trailing_whitespace() -> None:
    # the cut lands on trailing whitespace (positions 82-84 are spaces):
    # rstrip() must remove them so the ellipsis never follows a gap
    source = "a" * 82 + "   " + "b" * 4  # 89 chars total
    title, _ = build_automatic_metadata(source)

    assert title == "a" * 82 + "..." + " — Highlight"
    assert len(title) == 97
    assert "   " not in title


def test_build_automatic_metadata_unicode_counts_characters_not_bytes() -> None:
    source = "é" * 89
    title, _ = build_automatic_metadata(source)

    assert len(title) == 100
    assert title.endswith(" — Highlight")


# ---------------------------------------------------------------------------
# _classify_job_state(): uploaded/rendered/processing DB rows without
# filesystem markers
# ---------------------------------------------------------------------------


def test_production_status_uploaded_row_without_receipt_is_uploaded_private(
    speech_video: Path, tmp_path: Path
) -> None:
    """A job whose DB row says status == "uploaded" is reported as
    uploaded_private even when no local receipt marker exists - the DB
    row itself is authoritative that the upload finished."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True, status="uploaded")
    settings = _fake_settings(tmp_path / "work")

    status = production_status(repo, settings)

    assert status.uploaded_private == 1
    assert status.jobs[0].state == "uploaded_private"


@pytest.mark.parametrize("excluded_status", ["rendered", "processing", "failed"])
def test_production_status_non_eligible_row_without_artifacts_is_inactive(
    excluded_status: str, speech_video: Path, tmp_path: Path
) -> None:
    """A rights-confirmed row in any non-pending status (rendered,
    processing, failed) with no filesystem markers must NOT be reported
    as rights_approved_eligible - run_production_once() would never
    select it, so the status report must not promise it is eligible. It
    is "inactive", not "rejected": its rights were never rejected."""
    repo = FakeRepository()
    repo.seed(
        job_id=1,
        source_path=str(speech_video),
        rights_confirmed=True,
        status=excluded_status,
    )
    settings = _fake_settings(tmp_path / "work")

    status = production_status(repo, settings)

    assert status.rights_approved_eligible == 0
    assert status.rejected == 0
    assert status.inactive == 1
    assert status.jobs[0].state == "inactive"


def test_production_status_receipt_marker_precedes_db_status(
    speech_video: Path, tmp_path: Path, patched_recognizer: type[FakeRecognizer]
) -> None:
    """A receipt-bearing job stays "uploaded_private" regardless of what
    its DB status says (file-based markers take precedence)."""
    repo = FakeRepository()
    repo.seed(job_id=1, source_path=str(speech_video), rights_confirmed=True, status="processing")
    settings = _fake_settings(tmp_path / "work")

    packaged = run_production(1, 1, repo, settings)
    assert packaged.package is not None
    _write_marker(packaged.package.package_dir, "upload_receipt.json")

    status = production_status(repo, settings)

    assert status.uploaded_private == 1
    assert status.processing == 0
    assert status.jobs[0].state == "uploaded_private"
