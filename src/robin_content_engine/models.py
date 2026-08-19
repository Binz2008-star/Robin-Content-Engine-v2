from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


class VideoJob(BaseModel):
    id: int
    source_path: str | None = None
    source_url: str | None = None
    source_title: str
    rights_confirmed: bool
    rights_note: str | None = None
    attempts: int = 0

    @model_validator(mode="after")
    def require_source(self) -> "VideoJob":
        if not self.source_path and not self.source_url:
            raise ValueError("A job requires source_path or source_url")
        return self

    def local_source(self) -> Path:
        if not self.source_path:
            raise ValueError("Remote source ingestion is not enabled in the MVP")
        path = Path(self.source_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Source file does not exist: {path}")
        return path


class GeneratedContent(BaseModel):
    title: str = Field(min_length=8, max_length=100)
    description: str = Field(min_length=20, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    script: str = Field(min_length=20, max_length=1200)

    @field_validator("title", "description", "script")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = " ".join(value.split()).strip().lstrip("#")[:50]
            key = tag.casefold()
            if tag and key not in seen:
                cleaned.append(tag)
                seen.add(key)
        return cleaned[:20]


class RankedCandidateResult(BaseModel):
    """One entry of an AI-generated highlight re-ranking response: the
    candidate's original 1-based rank (as assigned by the deterministic
    highlight analysis), a short spoken "hook" line (a later PR burns it in
    as the opening caption), and a short placement justification."""

    candidate: int = Field(ge=1)
    hook: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("hook", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split()).strip()


class CandidateRankingResult(BaseModel):
    """The validated JSON contract for an AI highlight re-ranking: an
    ordered list of RankedCandidateResult entries, first = best. Full
    coverage - every candidate listed exactly once - cannot be expressed as
    a pydantic constraint (the candidate count is only known at call time),
    so ai_logic.py enforces it with a deterministic validator before the
    response is accepted."""

    ranking: list[RankedCandidateResult] = Field(min_length=1)


class RenderResult(BaseModel):
    output_path: Path
    duration_seconds: float = Field(gt=0, le=60.5)


class UploadResult(BaseModel):
    youtube_id: str = Field(min_length=6, max_length=32)
    privacy_status: str


class HighlightCandidateResult(BaseModel):
    rank: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    score: float
    signals: dict[str, float]
    reason: str


class HighlightScanResult(BaseModel):
    job_id: int
    source_title: str
    duration_seconds: float
    candidates: list[HighlightCandidateResult]
