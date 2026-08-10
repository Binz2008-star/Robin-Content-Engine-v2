from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from faster_whisper import WhisperModel


class TranscriptionError(Exception):
    pass


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


class SpeechRecognizer(Protocol):
    def transcribe(self, media_path: Path) -> list[TranscriptSegment]: ...


class FasterWhisperRecognizer:
    """Local, CPU-only speech-to-text via faster-whisper (int8 compute
    type, no CUDA/GPU assumption) - the ADOPT choice from the Phase 7A ASR
    benchmark protocol for the operator's AMD RX 6800 XT Windows machine,
    which has no verified CUDA/Vulkan path for this library.

    The underlying WhisperModel is lazy-loaded on first use, so
    constructing this class never triggers a network call or model
    download by itself - only calling transcribe() does.
    """

    def __init__(
        self, model_size: str = "base", *, device: str = "cpu", compute_type: str = "int8"
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )
        return self._model

    def transcribe(self, media_path: Path) -> list[TranscriptSegment]:
        if not media_path.is_file():
            raise TranscriptionError(f"Media file does not exist: {media_path}")

        model = self._get_model()
        segments_iter, _info = model.transcribe(str(media_path))
        return [
            TranscriptSegment(
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
                text=segment.text.strip(),
            )
            for segment in segments_iter
        ]
