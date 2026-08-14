from pathlib import Path

import structlog

from .ai_logic import ContentGenerator
from .config import Settings
from .database import JobRepository
from .models import VideoJob
from .tts import VoiceGenerator
from .uploader import YouTubeUploader
from .video_editor import ShortsRenderer

log = structlog.get_logger()


class ContentEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = JobRepository(
            database_url=settings.database_url,
            max_attempts=settings.max_job_attempts,
        )
        self.content_generator = ContentGenerator(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )
        self.voice_generator = VoiceGenerator(
            voice=settings.tts_voice,
            rate=settings.tts_rate,
            volume=settings.tts_volume,
            pitch=settings.tts_pitch,
        )
        self.renderer = ShortsRenderer(
            max_seconds=settings.max_short_seconds,
            original_audio_volume=settings.original_audio_volume,
        )
        self.uploader = YouTubeUploader(
            client_secret_file=settings.youtube_client_secret_file,
            token_file=settings.youtube_token_file,
            privacy_status="private",
            category_id=settings.youtube_category_id,
        )

    async def run_once(self, *, upload: bool = True) -> int | None:
        self.settings.ensure_runtime_dirs()
        with self.repository.running():
            quarantined = self.repository.quarantine_unconfirmed()
            if quarantined:
                log.warning("jobs_quarantined", count=quarantined)

            job = self.repository.claim_next()
            if job is None:
                log.info("queue_empty")
                return None

            try:
                return await self._process(job, upload=upload)
            except Exception as exc:
                self.repository.mark_failed(job.id, exc)
                log.exception("job_failed", job_id=job.id, error=str(exc))
                raise

    async def run_job(self, job_id: int, *, upload: bool = False) -> int | None:
        self.settings.ensure_runtime_dirs()
        with self.repository.running():
            job_row = self.repository.get_job(job_id)
            if job_row is None:
                return None
            job = VideoJob.model_validate(job_row)
            try:
                return await self._process(job, upload=upload)
            except Exception as exc:
                self.repository.mark_failed(job.id, exc)
                log.exception("job_failed", job_id=job.id, error=str(exc))
                raise

    async def _process(self, job: VideoJob, *, upload: bool) -> int:
        if not job.rights_confirmed:
            raise PermissionError("Publishing rights are not confirmed")

        source_path = job.local_source()
        job_dir = self.settings.work_dir / str(job.id)
        voice_path = job_dir / "voice.mp3"
        output_path = job_dir / "final.mp4"

        context = self._build_context(job, source_path)
        generated = self.content_generator.generate(context)
        await self.voice_generator.generate(generated.script, voice_path)
        render = self.renderer.render(source_path, voice_path, output_path)
        self.repository.mark_rendered(job.id, generated, render.output_path)
        log.info(
            "job_rendered",
            job_id=job.id,
            duration=render.duration_seconds,
            output=str(render.output_path),
        )

        if not upload:
            return job.id

        uploaded = self.uploader.upload(render.output_path, generated)
        self.repository.mark_uploaded(job.id, uploaded.youtube_id)
        voice_path.unlink(missing_ok=True)
        log.info(
            "job_uploaded",
            job_id=job.id,
            youtube_id=uploaded.youtube_id,
            privacy=uploaded.privacy_status,
        )
        return job.id

    @staticmethod
    def _build_context(job: VideoJob, source_path: Path) -> str:
        note = job.rights_note or "The publisher confirmed ownership or a valid licence."
        return (
            f"Source title: {job.source_title}\n"
            f"File name: {source_path.name}\n"
            f"Rights note: {note}\n"
            "Create an original commentary angle instead of describing content "
            "from another creator."
        )
