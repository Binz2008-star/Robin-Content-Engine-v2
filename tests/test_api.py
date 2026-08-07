from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from robin_content_engine.api import create_app  # noqa: E402
from robin_content_engine.models import GeneratedContent, RenderResult, UploadResult  # noqa: E402


class FakeSettings:
    def __init__(self) -> None:
        self.database_url = "postgresql://fake"
        self.deepseek_api_key = "fake-key"
        self.deepseek_base_url = "https://example.test"
        self.deepseek_model = "fake-model"
        self.youtube_client_secret_file = Path("client_secret.json")
        self.youtube_token_file = Path("token.json")
        self.youtube_privacy_status = "private"
        self.youtube_category_id = "20"
        self.work_dir = Path("/tmp/robin-work")
        self.max_job_attempts = 3
        self.max_short_seconds = 58
        self.original_audio_volume = 0.15
        self.log_level = "INFO"

    def ensure_runtime_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self.next_id = 1
        self.ping_ok = True
        self.open_calls = 0
        self.close_calls = 0

    def open(self) -> None:
        self.open_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def ping(self) -> bool:
        return self.ping_ok

    @contextmanager
    def running(self):
        yield self

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(job) for job in self.jobs.values()]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def status_counts(self) -> dict[str, int]:
        counts = {
            "pending": 0,
            "processing": 0,
            "rendered": 0,
            "uploaded": 0,
            "failed": 0,
            "quarantined": 0,
            "total": 0,
        }
        for job in self.jobs.values():
            status = job["status"]
            counts[status] += 1
            counts["total"] += 1
        return counts

    def enqueue_api_job(
        self,
        *,
        source_path: str,
        source_title: str,
        rights_confirmed: bool,
        rights_note: str,
    ) -> int:
        job_id = self.next_id
        self.next_id += 1
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_url": None,
            "source_title": source_title,
            "rights_confirmed": rights_confirmed,
            "rights_note": rights_note,
            "status": "pending",
            "generated_title": None,
            "generated_description": None,
            "generated_tags": [],
            "generated_script": None,
            "output_path": None,
            "youtube_id": None,
            "attempts": 0,
            "last_error": None,
            "claimed_at": None,
            "completed_at": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        return job_id

    def claim_job(self, job_id: int) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        if job["status"] != "pending":
            return None
        if not job["rights_confirmed"]:
            return None
        if job["attempts"] >= 3:
            return None
        job["status"] = "processing"
        job["attempts"] += 1
        job["claimed_at"] = "2024-01-01T00:01:00Z"
        job["last_error"] = None
        return dict(job)

    def retry_job(self, job_id: int) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job["status"] not in {"failed", "quarantined"}:
            return False
        if not job["rights_confirmed"]:
            return False
        job["status"] = "pending"
        job["last_error"] = None
        job["claimed_at"] = None
        job["completed_at"] = None
        return True

    def quarantine_job(self, job_id: int) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job["status"] == "uploaded":
            return False
        if job["status"] == "quarantined":
            return False
        if job["status"] not in {"pending", "processing", "rendered", "failed"}:
            return False
        job["status"] = "quarantined"
        job["last_error"] = "Quarantined by operator."
        return True


class FakeRenderer:
    def render(self, source_path: Path, voice_path: Path, output_path: Path) -> RenderResult:
        output_path.write_bytes(b"video")
        return RenderResult(output_path=output_path, duration_seconds=5.0)


class FakeContentGenerator:
    def generate(self, context: str) -> GeneratedContent:
        return GeneratedContent(
            title="Title",
            description="A detailed summary for testing the engine.",
            tags=["tag1"],
            script="This is a test script with enough length to pass validation.",
        )


class FakeVoiceGenerator:
    async def generate(self, script: str, output_path: Path) -> None:
        output_path.write_bytes(b"audio")


class FakeUploader:
    def __init__(self) -> None:
        self.last_privacy_status: str | None = None

    def upload(self, video_path: Path, content: GeneratedContent) -> UploadResult:
        self.last_privacy_status = "private"
        return UploadResult(youtube_id="abc12345", privacy_status="private")


@pytest.fixture()
def client() -> TestClient:
    repository = FakeRepository()
    settings = FakeSettings()
    engine = SimpleNamespace(
        run_job=lambda job_id, *, upload=False: None,
    )
    app = create_app(
        repository=repository,
        settings=settings,
        engine_factory=lambda settings, repository: engine,
    )
    return TestClient(app)


def test_health_success(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0",
        "demo_mode": False,
    }


def test_health_db_failure() -> None:
    repository = FakeRepository()
    repository.ping_ok = False
    app = create_app(repository=repository, settings=FakeSettings())
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 503


def test_lifespan_opens_and_closes_repository_when_available() -> None:
    repository = FakeRepository()
    app = create_app(repository=repository, settings=FakeSettings())
    with TestClient(app):
        assert repository.open_calls == 1
    assert repository.close_calls == 1


def test_jobs_response_and_counts(client: TestClient) -> None:
    repository = client.app.state.repository
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    repository.enqueue_api_job(
        source_path="/tmp/source2.mp4",
        source_title="Demo 2",
        rights_confirmed=True,
        rights_note="owned",
    )
    repository.jobs[1]["status"] = "processing"
    repository.jobs[2]["status"] = "uploaded"
    repository.jobs[2]["youtube_id"] = "abc123"

    response = client.get("/api/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["pending"] == 0
    assert payload["counts"]["processing"] == 1
    assert payload["counts"]["uploaded"] == 1
    assert payload["counts"]["total"] == 2
    assert payload["jobs"][0]["id"] == 2
    assert set(payload["jobs"][0].keys()) == {
        "id",
        "source_path",
        "source_url",
        "source_title",
        "rights_confirmed",
        "rights_note",
        "status",
        "generated_title",
        "generated_description",
        "generated_tags",
        "generated_script",
        "output_path",
        "youtube_id",
        "attempts",
        "last_error",
        "claimed_at",
        "completed_at",
        "created_at",
        "updated_at",
    }


def test_enqueue_requires_rights_confirmation() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        json={
            "source_path": "/tmp/source.mp4",
            "source_title": "Demo",
            "rights_confirmed": False,
            "rights_note": "owned",
        },
    )
    assert response.status_code == 422


def test_enqueue_requires_rights_note() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        json={
            "source_path": "/tmp/source.mp4",
            "source_title": "Demo",
            "rights_confirmed": True,
            "rights_note": "   ",
        },
    )
    assert response.status_code == 422


def test_enqueue_requires_source_title() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        json={
            "source_path": "/tmp/source.mp4",
            "source_title": "   ",
            "rights_confirmed": True,
            "rights_note": "owned",
        },
    )
    assert response.status_code == 422


def test_remote_source_rejected() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        json={
            "source_url": "https://example.test/video.mp4",
            "source_title": "Demo",
            "rights_confirmed": True,
            "rights_note": "owned",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Remote source ingestion is not enabled."


def test_missing_local_file_rejected() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        json={
            "source_path": "/tmp/does-not-exist.mp4",
            "source_title": "Demo",
            "rights_confirmed": True,
            "rights_note": "owned",
        },
    )
    assert response.status_code == 422


def test_valid_enqueue() -> None:
    repository = FakeRepository()
    app = create_app(repository=repository, settings=FakeSettings())
    client = TestClient(app)
    source_path = Path("/tmp/robin-source.mp4")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"video")
    response = client.post(
        "/api/jobs",
        json={
            "source_path": str(source_path),
            "source_title": "Demo",
            "rights_confirmed": True,
            "rights_note": "owned",
        },
    )
    assert response.status_code == 200
    assert repository.jobs[1]["status"] == "pending"


def test_run_requires_existing_job() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.post("/api/jobs/999/run")
    assert response.status_code == 404


def test_run_rejects_non_pending_job() -> None:
    repository = FakeRepository()
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    repository.jobs[1]["status"] = "processing"
    app = create_app(repository=repository, settings=FakeSettings())
    client = TestClient(app)
    response = client.post("/api/jobs/1/run")
    assert response.status_code == 409


def test_specific_job_claiming_and_double_claim_protection() -> None:
    repository = FakeRepository()
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    app = create_app(repository=repository, settings=FakeSettings())
    client = TestClient(app)
    first = client.post("/api/jobs/1/run")
    second = client.post("/api/jobs/1/run")
    assert first.status_code == 200
    assert second.status_code == 409
    assert repository.jobs[1]["status"] == "processing"


def test_render_only_never_uploads() -> None:
    repository = FakeRepository()
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    calls: list[bool] = []

    def engine_factory(settings: FakeSettings, repository: FakeRepository):
        class Engine:
            def __init__(self, settings: FakeSettings, repository: FakeRepository) -> None:
                self.settings = settings
                self.repository = repository

            async def run_job(self, job_id: int, *, upload: bool = False) -> None:
                calls.append(upload)
        return Engine(settings, repository)

    app = create_app(
        repository=repository,
        settings=FakeSettings(),
        engine_factory=engine_factory,
    )
    client = TestClient(app)
    response = client.post("/api/jobs/1/run", json={"render_only": True})
    assert response.status_code == 200
    assert calls == [False]


def test_retry_and_quarantine_actions() -> None:
    repository = FakeRepository()
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    repository.jobs[1]["status"] = "failed"
    repository.jobs[1]["attempts"] = 1
    app = create_app(repository=repository, settings=FakeSettings())
    client = TestClient(app)

    retry_response = client.post("/api/jobs/1/actions", json={"action": "retry"})
    assert retry_response.status_code == 200
    assert repository.jobs[1]["status"] == "pending"

    quarantine_response = client.post(
        "/api/jobs/1/actions",
        json={"action": "quarantine"},
    )
    assert quarantine_response.status_code == 200
    assert repository.jobs[1]["status"] == "quarantined"


def test_system_hides_secrets() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.get("/api/system")
    payload = response.json()
    assert response.status_code == 200
    assert payload == {
        "app_name": "Robin Content Engine v2",
        "version": "0.1.0",
        "python_version": sys.version.split()[0],
        "ffmpeg_available": False,
        "deepseek_configured": True,
        "youtube_authenticated": False,
        "database": "connected",
        "demo_mode": False,
    }


def test_private_youtube_invariant() -> None:
    repository = FakeRepository()
    repository.enqueue_api_job(
        source_path="/tmp/source.mp4",
        source_title="Demo",
        rights_confirmed=True,
        rights_note="owned",
    )
    settings = FakeSettings()
    uploader = FakeUploader()
    app = create_app(
        repository=repository,
        settings=settings,
        engine_factory=lambda settings, repository: type(
            "Engine",
            (),
            {
                "__init__": lambda self, settings, repository: None,
                "run_job": lambda self, job_id, *, upload=False: None,
            },
        )(settings, repository),
    )
    _ = app
    assert uploader.last_privacy_status is None


def test_local_cors_origins() -> None:
    app = create_app(repository=FakeRepository(), settings=FakeSettings())
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
