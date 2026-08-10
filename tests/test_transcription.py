from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import transcription as transcription_module  # noqa: E402
from robin_content_engine.transcription import (  # noqa: E402
    FasterWhisperRecognizer,
    TranscriptionError,
)


@dataclass
class _FakeWhisperSegment:
    start: float
    end: float
    text: str


class _FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel - never touches the
    network or loads a real model, so these tests never require the real
    dependency's model download (blocked by this sandbox's egress
    policy)."""

    instances: ClassVar[list[_FakeWhisperModel]] = []

    def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        _FakeWhisperModel.instances.append(self)

    def transcribe(self, media_path: str) -> tuple[list[_FakeWhisperSegment], object]:
        segments = [
            _FakeWhisperSegment(start=0.0, end=2.0, text=" hello there "),
            _FakeWhisperSegment(start=2.0, end=4.5, text="general kenobi"),
        ]
        return segments, object()


def test_does_not_construct_model_at_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcription_module, "WhisperModel", _FakeWhisperModel)
    _FakeWhisperModel.instances.clear()

    FasterWhisperRecognizer(model_size="tiny")

    assert _FakeWhisperModel.instances == []


def test_rejects_missing_media_file_without_loading_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(transcription_module, "WhisperModel", _FakeWhisperModel)
    _FakeWhisperModel.instances.clear()
    recognizer = FasterWhisperRecognizer(model_size="tiny")

    with pytest.raises(TranscriptionError, match="does not exist"):
        recognizer.transcribe(tmp_path / "gone.mp4")

    assert _FakeWhisperModel.instances == []


def test_transcribe_strips_and_maps_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(transcription_module, "WhisperModel", _FakeWhisperModel)
    _FakeWhisperModel.instances.clear()
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"fake")

    recognizer = FasterWhisperRecognizer(model_size="base", device="cpu", compute_type="int8")
    segments = recognizer.transcribe(media_path)

    assert [s.text for s in segments] == ["hello there", "general kenobi"]
    assert segments[0].start_seconds == pytest.approx(0.0)
    assert segments[0].end_seconds == pytest.approx(2.0)
    assert segments[1].start_seconds == pytest.approx(2.0)
    assert segments[1].end_seconds == pytest.approx(4.5)

    assert len(_FakeWhisperModel.instances) == 1
    loaded = _FakeWhisperModel.instances[0]
    assert loaded.model_size == "base"
    assert loaded.device == "cpu"
    assert loaded.compute_type == "int8"


def test_reuses_loaded_model_across_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(transcription_module, "WhisperModel", _FakeWhisperModel)
    _FakeWhisperModel.instances.clear()
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"fake")

    recognizer = FasterWhisperRecognizer(model_size="tiny")
    recognizer.transcribe(media_path)
    recognizer.transcribe(media_path)

    assert len(_FakeWhisperModel.instances) == 1
