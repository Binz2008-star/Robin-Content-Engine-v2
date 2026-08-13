from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip

from .models import RenderResult


class ShortsRenderer:
    def __init__(self, max_seconds: int, original_audio_volume: float) -> None:
        self.max_seconds = max_seconds
        self.original_audio_volume = original_audio_volume

    def render(self, source_path: Path, voice_path: Path, output_path: Path) -> RenderResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        source = VideoFileClip(str(source_path))
        voice = AudioFileClip(str(voice_path))
        final = None
        final_audio = None

        try:
            if not source.duration or source.duration <= 0:
                raise ValueError("Source video has no usable duration")

            duration = min(float(source.duration), float(self.max_seconds))
            short = source.subclipped(0, duration)
            width, height = short.size
            target_ratio = 9 / 16

            if width / height > target_ratio:
                crop_width = int(height * target_ratio)
                short = short.cropped(x_center=width / 2, width=crop_width)
            else:
                crop_height = int(width / target_ratio)
                short = short.cropped(y_center=height / 2, height=crop_height)

            short = short.resized(new_size=(1080, 1920))
            audio_layers = []
            if short.audio is not None:
                audio_layers.append(short.audio.with_volume_scaled(self.original_audio_volume))

            voice_start = 0.35
            voice_duration = min(float(voice.duration or 0), max(duration - voice_start, 0.1))
            if voice_duration <= 0:
                raise ValueError("Generated voiceover has no usable duration")
            narration = voice.subclipped(0, voice_duration).with_start(voice_start)
            audio_layers.append(narration)

            final_audio = CompositeAudioClip(audio_layers).with_duration(duration)
            final = short.with_audio(final_audio)
            fps = min(max(int(getattr(short, "fps", 30) or 30), 24), 60)
            final.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=fps,
                preset="slow",  # Better quality encoding
                bitrate="4000k",  # Higher bitrate for better quality
                threads=4,
                pixel_format="yuv420p",
                ffmpeg_params=["-movflags", "+faststart", "-tune", "film"],  # Better quality tuning
                logger=None,
            )

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("Video render completed without producing output")
            return RenderResult(output_path=output_path, duration_seconds=duration)
        finally:
            if final is not None:
                final.close()
            if final_audio is not None:
                final_audio.close()
            voice.close()
            source.close()
