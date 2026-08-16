from __future__ import annotations

import json
import shutil
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from . import __version__
from .config import Settings
from .database import JobRepository


class SupportsPing(Protocol):
    def ping(self) -> bool: ...


class SupportsJobs(Protocol):
    def list_jobs(self) -> list[dict[str, Any]]: ...

    def get_job(self, job_id: int) -> dict[str, Any] | None: ...

    def status_counts(self) -> dict[str, int]: ...

    def enqueue_api_job(
        self,
        *,
        source_path: str,
        source_title: str,
        rights_confirmed: bool,
        rights_note: str,
    ) -> int: ...

    def claim_job(self, job_id: int) -> dict[str, Any] | None: ...

    def retry_job(self, job_id: int) -> bool: ...

    def quarantine_job(self, job_id: int) -> bool: ...


class SupportsEngine(Protocol):
    async def run_job(self, job_id: int, *, upload: bool = False) -> int | None: ...


class _NoOpEngine:
    async def run_job(self, job_id: int, *, upload: bool = False) -> int | None:
        return None


class JobCreateRequest(BaseModel):
    source_path: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    rights_confirmed: bool = False
    rights_note: str | None = None

    @field_validator("source_title")
    @classmethod
    def validate_source_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_title must not be empty")
        return cleaned

    @field_validator("rights_note")
    @classmethod
    def validate_rights_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("rights_note must not be empty")
        return cleaned

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_path must not be empty")
        return cleaned

    model_config = {"extra": "forbid"}


class JobActionRequest(BaseModel):
    action: str = Field(min_length=1)


class JobRunRequest(BaseModel):
    render_only: bool = False


def _youtube_token_is_valid(token_path: Path) -> bool:
    """Conservative local check: file exists, is valid JSON, and carries the
    fields google-auth's Credentials.from_authorized_user_info requires.
    Never makes a network call and never exposes file contents."""
    resolved = token_path.expanduser()
    try:
        if not resolved.is_file() or resolved.stat().st_size == 0:
            return False
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    required_fields = {"refresh_token", "client_id", "client_secret"}
    return required_fields.issubset(data.keys())


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "source_path": job.get("source_path"),
        "source_url": job.get("source_url"),
        "source_title": job["source_title"],
        "rights_confirmed": job["rights_confirmed"],
        "rights_note": job.get("rights_note"),
        "status": job["status"],
        "generated_title": job.get("generated_title"),
        "generated_description": job.get("generated_description"),
        "generated_tags": job.get("generated_tags", []),
        "generated_script": job.get("generated_script"),
        "output_path": job.get("output_path"),
        "youtube_id": job.get("youtube_id"),
        "attempts": job.get("attempts", 0),
        "last_error": job.get("last_error"),
        "claimed_at": job.get("claimed_at"),
        "completed_at": job.get("completed_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def create_app(
    *,
    repository: Any | None = None,
    settings: Settings | None = None,
    engine_factory: Callable[[Settings, Any], SupportsEngine] | None = None,
) -> FastAPI:
    app_settings: Settings = settings if settings is not None else Settings()  # type: ignore[call-arg]
    repo = repository or JobRepository(
        app_settings.database_url,
        app_settings.max_job_attempts,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if hasattr(repo, "open"):
            repo.open()
        try:
            yield
        finally:
            if hasattr(repo, "close"):
                repo.close()

    app = FastAPI(title="Robin Content Engine API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.repository = repo
    app.state.settings = app_settings

    def get_repository() -> Any:
        return app.state.repository

    def get_settings() -> Settings:
        return cast(Settings, app.state.settings)

    def get_engine() -> SupportsEngine:
        if engine_factory is not None:
            return engine_factory(app_settings, repo)
        if isinstance(app_settings, Settings):
            from .pipeline import ContentEngine

            return ContentEngine(app_settings)
        return _NoOpEngine()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            if repo.ping():
                return {
                    "status": "ok",
                    "database": "connected",
                    "version": __version__,
                    "demo_mode": False,
                }
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        )

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        jobs = [_job_payload(job) for job in repo.list_jobs()]
        jobs.sort(
            key=lambda job: (
                job.get("created_at") or "",
                job.get("id", 0),
            ),
            reverse=True,
        )
        counts = repo.status_counts()
        return {"jobs": jobs, "counts": counts}

    @app.post("/api/jobs", response_model=dict[str, Any])
    def create_job(payload: JobCreateRequest) -> dict[str, Any]:
        if payload.rights_confirmed is not True:
            raise HTTPException(status_code=422, detail="rights_confirmed must be true")
        if payload.source_url is not None:
            raise HTTPException(status_code=422, detail="Remote source ingestion is not enabled.")
        if not payload.source_path:
            raise HTTPException(status_code=422, detail="source_path is required")
        local_path = Path(payload.source_path).expanduser()
        if not local_path.is_file():
            raise HTTPException(status_code=422, detail="Source file does not exist")
        if not payload.source_title:
            raise HTTPException(status_code=422, detail="source_title is required")
        if not payload.rights_note:
            raise HTTPException(status_code=422, detail="rights_note is required")
        job_id = repo.enqueue_api_job(
            source_path=str(local_path),
            source_title=payload.source_title,
            rights_confirmed=payload.rights_confirmed,
            rights_note=payload.rights_note,
        )
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=500, detail="job creation failed")
        return _job_payload(job)

    @app.post("/api/jobs/{job_id}/run")
    async def run_job(
        job_id: int,
        payload: JobRunRequest | None = None,
        engine: Annotated[SupportsEngine, Depends(get_engine)] = Depends(get_engine),  # noqa: B008
    ) -> dict[str, Any]:
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job["status"] != "pending":
            raise HTTPException(status_code=409, detail="job is not pending")
        claimed = repo.claim_job(job_id)
        if claimed is None:
            raise HTTPException(status_code=409, detail="job could not be claimed")
        render_only = payload.render_only if payload else False
        await engine.run_job(job_id, upload=not render_only)
        # The job is processed synchronously inside this request - it is
        # NOT queued for a background worker (the legacy run-once
        # semantics), so the response must not claim otherwise.
        message = "Job processed synchronously." if render_only else "Job processed and published."
        return {
            "status": "success",
            "message": message,
            "job": _job_payload(repo.get_job(job_id) or claimed),
        }

    @app.post("/api/jobs/{job_id}/actions")
    def job_action(job_id: int, payload: JobActionRequest) -> dict[str, Any]:
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if payload.action == "retry":
            ok = repo.retry_job(job_id)
            if not ok:
                raise HTTPException(status_code=409, detail="retry not allowed")
        elif payload.action == "quarantine":
            ok = repo.quarantine_job(job_id)
            if not ok:
                raise HTTPException(status_code=409, detail="quarantine not allowed")
        else:
            raise HTTPException(status_code=422, detail="unsupported action")
        job = repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"status": "ok", "job": _job_payload(job)}

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        ffmpeg_path = shutil.which("ffmpeg")
        try:
            database_state = "connected" if repo.ping() else "unavailable"
        except Exception:
            database_state = "unavailable"
        deepseek_configured = bool(
            getattr(app_settings, "deepseek_api_key", None)
            and str(app_settings.deepseek_api_key).strip()
        )
        token_path = getattr(app_settings, "youtube_token_file", None)
        youtube_authenticated = token_path is not None and _youtube_token_is_valid(
            Path(token_path)
        )
        return {
            "app_name": "Robin Content Engine v2",
            "version": __version__,
            "python_version": sys.version.split()[0],
            "ffmpeg_available": bool(ffmpeg_path),
            "deepseek_configured": deepseek_configured,
            "youtube_authenticated": youtube_authenticated,
            "database": database_state,
            "demo_mode": False,
        }

    return app
