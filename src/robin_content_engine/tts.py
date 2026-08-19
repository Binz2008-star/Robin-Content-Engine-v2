from pathlib import Path

import edge_tts
from tenacity import retry, stop_after_attempt, wait_exponential


class VoiceGenerator:
    def __init__(
        self,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    async def generate(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        communicator = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )
        await communicator.save(str(output_path))
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("TTS completed without producing audio")
        return output_path
