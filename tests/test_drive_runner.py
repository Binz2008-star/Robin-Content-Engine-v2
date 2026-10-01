from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import drive_runner as dr  # noqa: E402
from robin_content_engine.clip_selector import HighlightCandidate  # noqa: E402
from robin_content_engine.drive_runner import (  # noqa: E402
    NEUTRAL_SOURCE_TITLE,
    ChannelVideo,
    DriveRunnerError,
    GameEvidence,
    detect_game_any,
    game_evidence,
    order_videos,
    produce_next_short,
    source_title_for,
)
from robin_content_engine.drive_source import (  # noqa: E402
    DriveArchive,
    DriveVideo,
    TakeoutListing,
)
from robin_content_engine.segment_ledger import UsedSegment, parse_ledger_url  # noqa: E402

PS5_FORTNITE = ChannelVideo(
    "MrZkqujTwdg", "Ggg", 6017, ("#PS5Live", "Fortnite", "Gg", "PlayStation 5")
)
PS4_APEX = ChannelVideo(
    "lj0g2NuYo3k", "Robin_CR8's Live PS4 Broadcast", 5509, ("#PS4Live", "Apex Legends")
)
AI_APEX = ChannelVideo("B7phw0z5GqI", "أبكس ليجندز.. جلسة نار 🔥", 7514, ("أبكس ليجندز",))
ARCHIVE = ChannelVideo("XqJcCA2aefg", "Archived Gaming Clip", 9277, ("archive", "gaming"))


def _cand(start: float, end: float) -> HighlightCandidate:
    return HighlightCandidate(start, end, 1.0, 0.0, 0.0, 0.0, "t")


# ---------------------------------------------------------------------------
# Game evidence and title truthfulness
# ---------------------------------------------------------------------------


def test_detect_game_any_handles_arabic_and_stays_conservative() -> None:
    assert detect_game_any("فورتنايت مع روبن 🔥") == "Fortnite"
    assert detect_game_any("أبيكس ليجندز | جلسة") == "Apex Legends"
    assert detect_game_any("Fortnite win") == "Fortnite"
    assert detect_game_any("Black ops") is None  # ambiguous capture name
    assert detect_game_any("لقطة من أرشيف القناة") is None


def test_console_native_tags_confirm_the_game() -> None:
    assert game_evidence(PS5_FORTNITE) == ("Fortnite", GameEvidence.CONFIRMED)
    assert game_evidence(PS4_APEX) == ("Apex Legends", GameEvidence.CONFIRMED)


def test_title_only_game_is_merely_claimed() -> None:
    assert game_evidence(AI_APEX) == ("Apex Legends", GameEvidence.CLAIMED)
    assert game_evidence(ARCHIVE) == (None, GameEvidence.NONE)


def test_only_confirmed_games_reach_the_source_title() -> None:
    assert source_title_for("Fortnite", GameEvidence.CONFIRMED) == "Fortnite gameplay"
    assert source_title_for("Apex Legends", GameEvidence.CLAIMED) == NEUTRAL_SOURCE_TITLE
    assert source_title_for(None, GameEvidence.NONE) == NEUTRAL_SOURCE_TITLE


def test_order_prefers_confirmed_then_priority_then_length() -> None:
    matched = {
        Path("a.mp4"): ARCHIVE,
        Path("b.mp4"): AI_APEX,
        Path("c.mp4"): PS4_APEX,
        Path("d.mp4"): PS5_FORTNITE,
    }

    order = [video.video_id for _p, video, _g, _e in order_videos(matched)]

    assert order == [
        PS5_FORTNITE.video_id,  # confirmed + top priority game
        PS4_APEX.video_id,  # confirmed
        AI_APEX.video_id,  # claimed
        ARCHIVE.video_id,  # no game
    ]


# ---------------------------------------------------------------------------
# End-to-end orchestration with fakes (no Drive, DB, media or upload)
# ---------------------------------------------------------------------------


class FakeRepository:
    enqueued: ClassVar[list[dict[str, Any]]] = []

    @contextmanager
    def running(self) -> Any:
        yield self

    def enqueue_local(
        self, source_path: Path, source_title: str, rights_note: str, source_url: str | None = None
    ) -> int:
        FakeRepository.enqueued.append(
            {"path": source_path, "title": source_title, "note": rights_note, "url": source_url}
        )
        return 100 + len(FakeRepository.enqueued)


def _settings(tmp_path: Path) -> Any:
    return SimpleNamespace(
        database_url="postgresql://fake",
        max_job_attempts=3,
        work_dir=tmp_path / "work",
        highlight_min_seconds=15.0,
        highlight_max_seconds=45.0,
    )


@pytest.fixture
def fake_drive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    FakeRepository.enqueued = []
    state: dict[str, Any] = {
        "used": {},
        "files": {},
        "downloads": [],
        "loose": [],
        "archives": [DriveArchive("arc1", "takeout-001.zip", 10)],
    }

    def fake_download(service: Any, archive: DriveArchive | DriveVideo, dest_dir: Path) -> Path:
        state["downloads"].append(archive.file_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / archive.name
        path.write_bytes(b"zip")
        return path

    def fake_extract(archive_path: Path, dest_dir: Path) -> list[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for name in state["files"]:
            p = dest_dir / name
            p.write_bytes(b"v")
            out.append(p)
        return out

    monkeypatch.setattr(
        dr,
        "list_takeout",
        lambda service, folder: TakeoutListing(state["archives"], state["loose"]),
    )
    monkeypatch.setattr(dr, "download_archive", fake_download)
    monkeypatch.setattr(dr, "extract_videos", fake_extract)
    monkeypatch.setattr(
        dr, "fetch_used_segments", lambda settings, vid: state["used"].get(vid, [])
    )
    return state


def _run(tmp_path: Path, state: dict[str, Any], **kwargs: Any) -> Any:
    produced: list[dict[str, Any]] = []

    def produce(job_id: int, rank: int, repo: Any, settings: Any, **kw: Any) -> Any:
        produced.append({"job_id": job_id, "rank": rank, **kw})
        return SimpleNamespace(final_video_path=Path("final.mp4"))

    result = produce_next_short(
        _settings(tmp_path),
        drive_service=object(),
        folder_id="folder",
        channel_videos=[PS5_FORTNITE, AI_APEX, ARCHIVE],
        candidates_fn=lambda path, top_n, **kw: [_cand(100, 130), _cand(400, 430)],
        produce_fn=produce,
        duration_fn=lambda p: state["files"].get(p.name),
        free_bytes_fn=lambda path: state.get("free", 10**12),
        repository_factory=FakeRepository,
        **kwargs,
    )
    return result, produced


def test_produces_from_confirmed_video_and_records_segment(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg.mp4": 6017.0, "Archived Gaming Clip.mp4": 9277.0}

    result, produced = _run(tmp_path, fake_drive)

    assert result is not None
    assert result.video_id == PS5_FORTNITE.video_id
    assert result.evidence is GameEvidence.CONFIRMED
    assert result.source_title == "Fortnite gameplay"
    assert (result.rank, result.start_seconds, result.end_seconds) == (1, 100, 130)
    job = FakeRepository.enqueued[0]
    assert parse_ledger_url(job["url"]) == UsedSegment(PS5_FORTNITE.video_id, 100, 130)
    assert "Game evidence: confirmed (Fortnite)" in job["note"]
    assert produced[0]["rank"] == 1
    assert produced[0]["analysis_cache_path"].name == f"drive-{PS5_FORTNITE.video_id}.json"
    # The downloaded archive is removed once extracted (runner disk budget).
    assert not (tmp_path / "work" / "drive" / "archives" / "takeout-001.zip").exists()


def test_skips_used_segments_and_moves_to_next_rank(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg.mp4": 6017.0}
    fake_drive["used"] = {PS5_FORTNITE.video_id: [UsedSegment(PS5_FORTNITE.video_id, 95, 125)]}

    result, produced = _run(tmp_path, fake_drive)

    assert result is not None
    assert (result.rank, result.start_seconds) == (2, 400)
    assert produced[0]["rank"] == 2


def test_claimed_game_gets_neutral_title(tmp_path: Path, fake_drive: dict[str, Any]) -> None:
    fake_drive["files"] = {"أبكس ليجندز.. جلسة نار 🔥.mp4": 7514.0}

    result, _ = _run(tmp_path, fake_drive)

    assert result is not None
    assert result.evidence is GameEvidence.CLAIMED
    assert result.source_title == NEUTRAL_SOURCE_TITLE
    assert FakeRepository.enqueued[0]["title"] == NEUTRAL_SOURCE_TITLE


def test_returns_none_when_everything_is_used_or_unmatched(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg.mp4": 6017.0, "Unknown upload.mp4": 12.0}
    fake_drive["used"] = {PS5_FORTNITE.video_id: [UsedSegment(PS5_FORTNITE.video_id, 0, 1000)]}

    result, produced = _run(tmp_path, fake_drive)

    assert result is None
    assert produced == []
    assert FakeRepository.enqueued == []


def test_empty_folder_is_a_clear_error(
    tmp_path: Path, fake_drive: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_drive["archives"] = []

    with pytest.raises(DriveRunnerError, match="shared with the service account"):
        _run(tmp_path, fake_drive)


# ---------------------------------------------------------------------------
# Loose Takeout videos (too large for a zip part, stored "<title>-NNN.mp4")
# ---------------------------------------------------------------------------


def test_loose_video_matches_despite_part_suffix_and_is_used_first(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg-026.mp4": 6017.0}
    fake_drive["loose"] = [DriveVideo("lv1", "Ggg-026.mp4", 5_000, None)]

    result, _ = _run(tmp_path, fake_drive)

    assert result is not None
    assert result.video_id == PS5_FORTNITE.video_id
    assert result.source_title == "Fortnite gameplay"
    # Produced straight from the loose file; no zip part was downloaded.
    assert fake_drive["downloads"] == ["lv1"]


def test_loose_video_with_unknown_title_is_never_downloaded(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["loose"] = [DriveVideo("lv1", "Some other upload-007.mp4", 5_000, 60.0)]

    result, _ = _run(tmp_path, fake_drive)

    assert result is None
    assert fake_drive["downloads"] == ["arc1"]


def test_loose_video_whose_drive_duration_contradicts_is_never_downloaded(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    # Title matches "Ggg" but Drive says 60s, not 6017s: not that video.
    fake_drive["loose"] = [DriveVideo("lv1", "Ggg-007.mp4", 5_000, 60.0)]

    result, _ = _run(tmp_path, fake_drive)

    assert result is None
    assert "lv1" not in fake_drive["downloads"]


def test_files_that_do_not_fit_on_disk_are_skipped_not_downloaded(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg.mp4": 6017.0}
    fake_drive["loose"] = [DriveVideo("big", "Ggg-021.mp4", 17 * 1024**3, None)]
    fake_drive["free"] = 14 * 1024**3

    result, _ = _run(tmp_path, fake_drive)

    # The 17 GB loose file is skipped; the small zip part still produces.
    assert result is not None
    assert fake_drive["downloads"] == ["arc1"]


def test_exhausted_loose_video_is_deleted_after_use(
    tmp_path: Path, fake_drive: dict[str, Any]
) -> None:
    fake_drive["files"] = {"Ggg-026.mp4": 6017.0}
    fake_drive["loose"] = [DriveVideo("lv1", "Ggg-026.mp4", 5_000, None)]
    fake_drive["used"] = {PS5_FORTNITE.video_id: [UsedSegment(PS5_FORTNITE.video_id, 0, 1000)]}

    result, _ = _run(tmp_path, fake_drive)

    assert result is None
    assert not (tmp_path / "work" / "drive" / "loose" / "Ggg-026.mp4").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_drive_produce_cli_requires_folder_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import click
    from typer.testing import CliRunner

    from robin_content_engine.cli import app as cli_app

    monkeypatch.delenv("DRIVE_TAKEOUT_FOLDER_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)

    no_folder = CliRunner().invoke(cli_app, ["drive-produce"])
    assert no_folder.exit_code != 0
    assert "DRIVE_TAKEOUT_FOLDER_ID" in click.unstyle(no_folder.output)

    no_key = CliRunner().invoke(cli_app, ["drive-produce", "--folder-id", "f"])
    assert no_key.exit_code == 2

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{not json")
    bad_key = CliRunner().invoke(cli_app, ["drive-produce", "--folder-id", "f"])
    assert bad_key.exit_code == 2
    # The (invalid) key content is never echoed back.
    assert "{not json" not in bad_key.output


def _fake_result(tmp_path: Path, *, gate_passed: bool = True) -> Any:
    production = SimpleNamespace(
        final_video_path=tmp_path / "final.mp4",
        quality_gate=SimpleNamespace(passed=gate_passed),
        package=SimpleNamespace(package_dir=tmp_path / "pkg") if gate_passed else None,
        source_title="Fortnite gameplay",
        hook=None,
    )
    return dr.DriveShortResult(
        video_id=PS5_FORTNITE.video_id,
        source_file=tmp_path / "Ggg.mp4",
        game="Fortnite",
        evidence=GameEvidence.CONFIRMED,
        source_title="Fortnite gameplay",
        rank=1,
        start_seconds=100.0,
        end_seconds=130.0,
        job_id=7,
        production=production,  # type: ignore[arg-type]
    )


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    from robin_content_engine import cli as cli_module

    calls: dict[str, Any] = {"produced": 0, "uploads": [], "marked": [], "dry": 0}
    settings = SimpleNamespace(
        database_url="db",
        max_job_attempts=3,
        youtube_max_uploads_per_day=2,
        youtube_client_secret_file=tmp_path / "cs.json",
        youtube_token_file=tmp_path / "token.json",
    )

    def fake_produce(s: Any, svc: Any, folder: str) -> Any:
        calls["produced"] += 1
        return calls["result"]

    class Repo:
        def __init__(self, *a: Any) -> None:
            pass

        @contextmanager
        def running(self) -> Any:
            yield self

        def record_direct_upload(self, job_id: int, youtube_id: str) -> bool:
            calls["marked"].append((job_id, youtube_id))
            return calls.get("recordable", True)

    def fake_upload(pkg: Any, title: str, desc: str, tags: Any, s: Any, auth: Any, up: Any) -> Any:
        calls["uploads"].append(pkg)
        return SimpleNamespace(youtube_id="NEWvid12345", privacy_status="private")

    def fake_dry(*a: Any) -> None:
        calls["dry"] += 1

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    monkeypatch.setattr(cli_module, "Settings", lambda: settings)
    monkeypatch.setattr(cli_module, "build_drive_service", lambda info: object())
    monkeypatch.setattr(cli_module, "produce_next_short", fake_produce)
    monkeypatch.setattr(cli_module, "db_upload_allowed", lambda s: calls.get("allowed", True))
    monkeypatch.setattr(
        cli_module, "build_production_metadata", lambda t, s, hook=None: ("T", "D", ["x"])
    )
    monkeypatch.setattr(cli_module, "dry_run", fake_dry)
    monkeypatch.setattr(cli_module, "execute_private_upload", fake_upload)
    monkeypatch.setattr(cli_module, "JobRepository", Repo)
    calls["result"] = _fake_result(tmp_path)
    return calls


def _invoke(*args: str) -> Any:
    from typer.testing import CliRunner

    from robin_content_engine.cli import app as cli_app

    return CliRunner().invoke(cli_app, ["drive-produce", "--folder-id", "f", *args])


def test_drive_produce_without_flag_only_dry_runs(cli_env: dict[str, Any]) -> None:
    result = _invoke("--json")

    assert result.exit_code == 0, result.output
    assert '"game_evidence": "confirmed"' in result.output
    assert "PUBLISH DRY RUN PASS" in result.output
    assert cli_env["dry"] == 1
    assert cli_env["uploads"] == [] and cli_env["marked"] == []


def test_drive_produce_uploads_and_records_in_queue(cli_env: dict[str, Any]) -> None:
    result = _invoke("--execute-private-upload")

    assert result.exit_code == 0, result.output
    assert "UPLOAD SUCCESS" in result.output
    assert len(cli_env["uploads"]) == 1
    assert cli_env["marked"] == [(7, "NEWvid12345")]


def test_drive_produce_fails_loudly_when_upload_not_recorded(cli_env: dict[str, Any]) -> None:
    cli_env["recordable"] = False

    result = _invoke("--execute-private-upload")

    assert result.exit_code == 1
    assert len(cli_env["uploads"]) == 1
    assert "daily cap will not count it" in result.output


def test_drive_produce_checks_cap_before_producing(cli_env: dict[str, Any]) -> None:
    cli_env["allowed"] = False

    result = _invoke("--execute-private-upload")

    assert result.exit_code == 0, result.output
    assert "DAILY UPLOAD CAP REACHED" in result.output
    assert cli_env["produced"] == 0
    assert cli_env["uploads"] == []


def test_drive_produce_never_uploads_a_failed_quality_gate(
    cli_env: dict[str, Any], tmp_path: Path
) -> None:
    cli_env["result"] = _fake_result(tmp_path, gate_passed=False)

    result = _invoke("--execute-private-upload")

    assert result.exit_code == 1
    assert cli_env["uploads"] == [] and cli_env["marked"] == []
