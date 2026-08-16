from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    tts_voice: str = "ar-AE-HamdanNeural"
    tts_rate: str = "+0%"
    tts_volume: str = "+0%"
    tts_pitch: str = "+0Hz"

    youtube_client_secret_file: Path = Path("client_secret.json")
    youtube_token_file: Path = Path("token.json")
    youtube_privacy_status: Literal["private", "unlisted", "public"] = "private"
    youtube_category_id: str = "20"
    youtube_expected_channel_id: str | None = None

    work_dir: Path = Path("work")
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    max_short_seconds: int = Field(default=58, ge=5, le=60)
    original_audio_volume: float = Field(default=0.15, ge=0.0, le=1.0)
    log_level: str = "INFO"

    capture_source_dir: Path = Path("./captures")
    capture_stability_wait_seconds: float = Field(default=2.0, ge=0.0, le=60.0)

    db_pool_min_size: int = Field(default=1, ge=1, le=10)
    db_pool_max_size: int = Field(default=5, ge=1, le=20)

    @field_validator("youtube_expected_channel_id", mode="before")
    @classmethod
    def normalize_optional_channel_id(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def ensure_runtime_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
