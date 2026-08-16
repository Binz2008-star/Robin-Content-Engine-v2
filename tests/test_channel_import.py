from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.channel_import import (  # noqa: E402
    ChannelImportError,
    download_channel_video,
)


class FakeYDL:
    def __init__(self, opts: dict, write_output: bool = True) -> None:
        self.opts = opts
        self.write_output = write_output
        self.calls: list[tuple[str, bool]] = []

    def __enter__(self) -> FakeYDL:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = True) -> dict:
        self.calls.append((url, download))
        video_id = url.rsplit("=", 1)[-1]
        if self.write_output:
            outtmpl = self.opts["outtmpl"].replace("%(ext)s", "mp4")
            Path(outtmpl).write_bytes(b"video-data")
        return {"id": video_id, "title": "Test video"}


def _install_fake_yt_dlp(monkeypatch: pytest.MonkeyPatch, ydl: FakeYDL) -> None:
    import sys as _sys

    def factory(opts: dict) -> FakeYDL:
        ydl.opts = opts
        return ydl

    monkeypatch.setitem(_sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=factory))


def _fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    import robin_content_engine.channel_import as ci

    monkeypatch.setattr(ci, "_ffmpeg_location", lambda: "C:/ffmpeg/bin")


def test_download_uses_ytdlp_and_returns_mp4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ydl = FakeYDL({})
    _install_fake_yt_dlp(monkeypatch, ydl)
    _fake_ffmpeg(monkeypatch)

    dest = tmp_path / "dl"
    dest.mkdir(parents=True, exist_ok=True)

    result = download_channel_video("vid123", dest)

    assert result == dest / "vid123.mp4"
    assert result.read_bytes() == b"video-data"
    assert ydl.calls[0][0] == "https://www.youtube.com/watch?v=vid123"
    assert "ffmpeg_location" in ydl.opts


def test_download_raises_without_yt_dlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys as _sys

    # A None entry in sys.modules makes `import yt_dlp` raise ImportError,
    # exactly as if the dependency were not installed.
    monkeypatch.setitem(_sys.modules, "yt_dlp", None)

    with pytest.raises(ChannelImportError, match="yt-dlp"):
        download_channel_video("vid123", tmp_path / "dl")


def test_download_fails_when_no_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "dl"
    dest.mkdir(parents=True, exist_ok=True)
    # The fake downloads nothing (write_output=False), so no vid123.* file
    # exists afterwards - the code must report the no-output-file case.
    ydl = FakeYDL({}, write_output=False)
    _install_fake_yt_dlp(monkeypatch, ydl)
    _fake_ffmpeg(monkeypatch)

    with pytest.raises(ChannelImportError, match="no output file"):
        download_channel_video("vid123", dest)
