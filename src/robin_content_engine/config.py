import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_app_root() -> Path:
    """The canonical application root. Overridable via the ROBIN_APP_ROOT
    environment variable (set by the scheduled-task launcher); otherwise
    derived from this file's own location - <root>/src/robin_content_engine/
    config.py - so Settings NEVER depends on the current working directory
    (the scheduled task used to chdir into the wrong repository, which made
    the relative ".env" path and relative defaults resolve against the
    wrong tree)."""
    override = os.environ.get("ROBIN_APP_ROOT")
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


APP_ROOT = resolve_app_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(APP_ROOT / ".env"),
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
    youtube_category_id: str = "20"
    youtube_expected_channel_id: str | None = None
    # When True, every successful upload is automatically flipped to
    # "public" immediately after the private upload + receipt complete.
    # The upload itself still goes out private first (the proven path);
    # this only adds the post-upload publish step.
    youtube_public_after_upload: bool = False
    # When True, production-run-once generates Arabic titles/descriptions
    # via DeepSeek (natural Gulf-Arabic style) instead of the deterministic
    # English " — Highlight" metadata. Falls back to the deterministic
    # metadata if the AI call fails, so the pipeline never breaks.
    youtube_ai_metadata: bool = False
    # Language for AI-generated metadata: "arabic" (Gulf Arabic, default)
    # or "english" (clear English aimed at a mixed UAE/international
    # audience, with mixed EN/AR hashtags).
    youtube_metadata_language: str = "arabic"

    work_dir: Path = Path("work")
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    max_short_seconds: int = Field(default=58, ge=5, le=60)
    original_audio_volume: float = Field(default=0.15, ge=0.0, le=1.0)
    log_level: str = "INFO"

    # Highlight-window bounds for the SHORTS production path. The default
    # selector minimum of 15s favours the shortest window around a hot bin
    # (mean-per-bin scoring), which produces clips that feel too short.
    # Raising the floor here makes produced Shorts carry more context.
    highlight_min_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    highlight_max_seconds: float = Field(default=60.0, ge=10.0, le=60.0)

    capture_source_dir: Path = Path(r"C:\Users\loyal\Videos\Captures")
    capture_stability_wait_seconds: float = Field(default=2.0, ge=0.0, le=60.0)

    @field_validator("youtube_expected_channel_id", mode="before")
    @classmethod
    def normalize_optional_channel_id(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("youtube_metadata_language")
    @classmethod
    def restrict_metadata_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("arabic", "english"):
            raise ValueError("youtube_metadata_language must be 'arabic' or 'english'")
        return normalized

    @model_validator(mode="after")
    def anchor_relative_paths(self) -> "Settings":
        """Resolve every relative filesystem path against APP_ROOT instead
        of the process's current working directory, so a launcher that
        happens to run from anywhere (e.g. the wrong repository) cannot
        silently redirect runtime files, OAuth credentials, or the capture
        source to the wrong location. Absolute configured values (e.g. a
        custom CAPTURE_SOURCE_DIR) are left untouched."""
        for attribute in (
            "work_dir",
            "youtube_client_secret_file",
            "youtube_token_file",
            "capture_source_dir",
        ):
            path: Path = getattr(self, attribute)
            if not path.is_absolute():
                setattr(self, attribute, (APP_ROOT / path).resolve())
        return self

    def ensure_runtime_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
