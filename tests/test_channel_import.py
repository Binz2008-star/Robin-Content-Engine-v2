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

    assert result.video_path == dest / "vid123.mp4"
    assert result.video_path.read_bytes() == b"video-data"
    assert ydl.calls[0][0] == "https://www.youtube.com/watch?v=vid123"
    assert "ffmpeg_location" in ydl.opts
    # without cookies: android client is tried first (reliable mp4), the
    # format asks for at most 1080p, and no cookiefile is passed
    assert ydl.opts["extractor_args"]["youtube"]["player_client"] == ["android", "web"]
    assert "height<=1080" in ydl.opts["format"]
    assert "cookiefile" not in ydl.opts


def test_download_with_cookies_prefers_web_clients_and_passes_cookiefile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ydl = FakeYDL({})
    _install_fake_yt_dlp(monkeypatch, ydl)
    _fake_ffmpeg(monkeypatch)

    dest = tmp_path / "dl"
    dest.mkdir(parents=True, exist_ok=True)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("dummy", encoding="utf-8")

    result = download_channel_video("vid123", dest, cookies_file=cookies)

    assert result.video_path == dest / "vid123.mp4"
    assert ydl.opts["cookiefile"] == str(cookies)
    assert ydl.opts["extractor_args"]["youtube"]["player_client"] == [
        "web",
        "web_safari",
        "tv",
        "android",
    ]


def test_download_returns_probed_resolution_when_file_already_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing download is returned without a network call, with its
    resolution probed from the file header."""
    import subprocess

    import imageio_ffmpeg

    dest = tmp_path / "dl"
    dest.mkdir(parents=True, exist_ok=True)
    existing = dest / "vid123.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=1280x720:r=24:d=1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(existing),
    ]
    result_sub = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result_sub.returncode == 0, result_sub.stderr

    calls: list[tuple[str, bool]] = []

    def exploding_factory(opts: dict) -> object:
        def extract_info(url: str, download: bool = True) -> dict:
            calls.append((url, download))
            raise AssertionError("existing download must never re-download")

        calls.clear()
        fake = SimpleNamespace(extract_info=extract_info)
        return fake

    _install_fake_yt_dlp(monkeypatch, SimpleNamespace(YoutubeDL=exploding_factory))

    result = download_channel_video("vid123", dest)

    assert result.video_path == existing
    assert result.width == 1280
    assert result.height == 720
    assert result.quality_label == "HD"
    assert calls == []


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
