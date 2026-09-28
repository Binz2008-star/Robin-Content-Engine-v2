from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import drive_source as ds  # noqa: E402
from robin_content_engine.drive_source import (  # noqa: E402
    ChannelVideoRef,
    DriveArchive,
    DriveSourceError,
    extract_videos,
    list_archives,
    match_all,
    match_channel_video,
    normalize_title,
)

# ---------------------------------------------------------------------------
# Fake Drive client
# ---------------------------------------------------------------------------


class _Exec:
    def __init__(self, value: Any) -> None:
        self.value = value

    def execute(self) -> Any:
        return self.value


class FakeFiles:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Exec:
        self.list_calls.append(kwargs)
        return _Exec(self.pages[len(self.list_calls) - 1])


class FakeService:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._files = FakeFiles(pages)

    def files(self) -> FakeFiles:
        return self._files


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


# ---------------------------------------------------------------------------
# list_archives
# ---------------------------------------------------------------------------


def test_list_archives_follows_pages_and_keeps_only_zips() -> None:
    service = FakeService(
        [
            {
                "files": [
                    {"id": "a", "name": "takeout-001.zip", "size": "100"},
                    {"id": "n", "name": "notes.txt", "size": "3"},
                ],
                "nextPageToken": "p2",
            },
            {"files": [{"id": "b", "name": "takeout-002.ZIP"}]},
        ]
    )

    archives = list_archives(service, "folder123")

    assert archives == [
        DriveArchive("a", "takeout-001.zip", 100),
        DriveArchive("b", "takeout-002.ZIP", None),
    ]
    calls = service.files().list_calls
    assert len(calls) == 2
    assert calls[0]["q"] == "'folder123' in parents and trashed = false"
    assert calls[1]["pageToken"] == "p2"


@pytest.mark.parametrize("bad", ["", "abc' or name contains 'x"])
def test_list_archives_rejects_bad_folder_id(bad: str) -> None:
    with pytest.raises(DriveSourceError, match="folder id"):
        list_archives(FakeService([]), bad)


# ---------------------------------------------------------------------------
# extract_videos
# ---------------------------------------------------------------------------


def test_extract_videos_keeps_only_video_files(tmp_path: Path) -> None:
    archive = _zip(
        tmp_path / "t.zip",
        {
            "Takeout/YouTube and YouTube Music/videos/Fortnite win.mp4": b"v1",
            "Takeout/YouTube and YouTube Music/videos/Apex run.MOV": b"v2",
            "Takeout/YouTube and YouTube Music/video metadata/videos.csv": b"csv",
            "Takeout/archive_browser.html": b"html",
        },
    )

    out = extract_videos(archive, tmp_path / "out")

    assert sorted(p.name for p in out) == ["Apex run.MOV", "Fortnite win.mp4"]
    assert (tmp_path / "out" / "Fortnite win.mp4").read_bytes() == b"v1"
    assert not (tmp_path / "out" / "videos.csv").exists()


@pytest.mark.parametrize("evil", ["../escape.mp4", "/abs/escape.mp4", "a/../../escape.mp4"])
def test_extract_videos_refuses_zip_slip(tmp_path: Path, evil: str) -> None:
    archive = _zip(tmp_path / "evil.zip", {evil: b"x"})

    with pytest.raises(DriveSourceError, match="unsafe archive entry"):
        extract_videos(archive, tmp_path / "out")
    assert not (tmp_path / "escape.mp4").exists()


def test_extract_videos_rejects_non_zip(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.zip"
    bogus.write_bytes(b"not a zip")

    with pytest.raises(DriveSourceError, match="not a valid zip"):
        extract_videos(bogus, tmp_path / "out")


def test_extract_videos_is_idempotent(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "t.zip", {"videos/a.mp4": b"abc"})
    first = extract_videos(archive, tmp_path / "out")
    mtime = first[0].stat().st_mtime_ns

    second = extract_videos(archive, tmp_path / "out")

    assert second == first
    assert second[0].stat().st_mtime_ns == mtime  # not rewritten


# ---------------------------------------------------------------------------
# download_archive
# ---------------------------------------------------------------------------


def test_download_archive_reuses_complete_file(tmp_path: Path) -> None:
    existing = tmp_path / "takeout-001.zip"
    existing.write_bytes(b"12345")

    class NoCallService:
        def files(self) -> Any:
            raise AssertionError("must not hit Drive for a complete local copy")

    path = ds.download_archive(
        NoCallService(), DriveArchive("a", "takeout-001.zip", 5), tmp_path
    )

    assert path == existing


def test_download_archive_cleans_partial_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Media:
        def get_media(self, **kwargs: Any) -> object:
            return object()

    class Service:
        def files(self) -> Media:
            return Media()

    class BrokenDownloader:
        def __init__(self, handle: Any, request: Any, chunksize: int) -> None:
            handle.write(b"half")

        def next_chunk(self, num_retries: int = 0) -> tuple[None, bool]:
            raise OSError("connection reset")

    import googleapiclient.http

    monkeypatch.setattr(googleapiclient.http, "MediaIoBaseDownload", BrokenDownloader)

    with pytest.raises(DriveSourceError, match="connection reset"):
        ds.download_archive(Service(), DriveArchive("a", "t.zip", 10), tmp_path)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Title normalization and matching
# ---------------------------------------------------------------------------


def test_normalize_title_handles_arabic_emoji_and_takeout_suffixes() -> None:
    assert normalize_title("فورتنايت مع روبن 🔥.mp4") == normalize_title("فورتنايت مع روبن 🔥")
    assert normalize_title("Archived Gaming Clip(3).mp4") == "archivedgamingclip"
    assert normalize_title("Fortnite: Epic_Win!") == normalize_title("Fortnite Epic Win")
    assert normalize_title("🔥🔥") == ""


_CANDIDATES = [
    ChannelVideoRef("uniq1", "فورتنايت مع روبن - جلسة", 1935),
    ChannelVideoRef("dupA", "Archived Gaming Clip", 9277),
    ChannelVideoRef("dupB", "Archived Gaming Clip", 7235),
    ChannelVideoRef("dupC", "Archived Gaming Clip", 7236),  # within tolerance of dupB
    ChannelVideoRef("nodur", "Old Clip from 2016", None),
]


def test_unique_title_matches_without_duration() -> None:
    ref = match_channel_video("فورتنايت مع روبن - جلسة.mp4", None, _CANDIDATES)

    assert ref is not None and ref.video_id == "uniq1"


def test_unique_title_with_contradicting_duration_is_refused() -> None:
    assert match_channel_video("فورتنايت مع روبن - جلسة.mp4", 60.0, _CANDIDATES) is None


def test_unique_title_matches_when_channel_duration_unknown() -> None:
    ref = match_channel_video("Old Clip from 2016.mp4", 7.0, _CANDIDATES)

    assert ref is not None and ref.video_id == "nodur"


def test_duplicate_titles_resolved_only_by_unambiguous_duration() -> None:
    ref = match_channel_video("Archived Gaming Clip(1).mp4", 9276.4, _CANDIDATES)
    assert ref is not None and ref.video_id == "dupA"

    # Two same-title videos within tolerance -> ambiguous -> never guessed.
    assert match_channel_video("Archived Gaming Clip.mp4", 7235.5, _CANDIDATES) is None
    # Duplicate title without a duration -> never guessed.
    assert match_channel_video("Archived Gaming Clip.mp4", None, _CANDIDATES) is None


def test_unknown_or_empty_titles_do_not_match() -> None:
    assert match_channel_video("Something else.mp4", 10.0, _CANDIDATES) is None
    assert match_channel_video("🔥.mp4", 10.0, _CANDIDATES) is None


def test_match_all_refuses_two_files_claiming_one_video() -> None:
    files = [
        (Path("فورتنايت مع روبن - جلسة.mp4"), None),
        (Path("فورتنايت مع روبن - جلسة(1).mp4"), None),
        (Path("Archived Gaming Clip.mp4"), 9277.0),
        (Path("Nope.mp4"), 3.0),
    ]

    matched, unmatched = match_all(files, _CANDIDATES)

    assert {p.name: r.video_id for p, r in matched.items()} == {
        "Archived Gaming Clip.mp4": "dupA"
    }
    assert sorted(p.name for p in unmatched) == sorted(
        ["فورتنايت مع روبن - جلسة.mp4", "فورتنايت مع روبن - جلسة(1).mp4", "Nope.mp4"]
    )
