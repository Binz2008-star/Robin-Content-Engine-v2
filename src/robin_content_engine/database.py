import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .models import GeneratedContent, VideoJob


class JobRepository:
    def __init__(self, database_url: str, max_attempts: int) -> None:
        self.max_attempts = max_attempts
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=False,
        )

    def open(self) -> None:
        self.pool.open(wait=True)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def running(self) -> Iterator["JobRepository"]:
        self.open()
        try:
            yield self
        finally:
            self.close()

    def ping(self) -> bool:
        with self.pool.connection() as conn:
            conn.execute("SELECT 1")
        return True

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, source_path, source_url, source_title, rights_confirmed,
                       rights_note, status, generated_title, generated_description,
                       generated_tags, generated_script, output_path, youtube_id,
                       attempts, last_error, claimed_at, completed_at, created_at,
                       updated_at
                FROM video_queue
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, source_path, source_url, source_title, rights_confirmed,
                       rights_note, status, generated_title, generated_description,
                       generated_tags, generated_script, output_path, youtube_id,
                       attempts, last_error, claimed_at, completed_at, created_at,
                       updated_at
                FROM video_queue
                WHERE id = %s
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def status_counts(self) -> dict[str, int]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM video_queue
                GROUP BY status
                """
            ).fetchall()
        counts = {
            "pending": 0,
            "processing": 0,
            "rendered": 0,
            "uploaded": 0,
            "failed": 0,
            "quarantined": 0,
            "total": 0,
        }
        for row in rows:
            status = row["status"]
            counts[status] = int(row["count"])
            counts["total"] += int(row["count"])
        return counts

    def enqueue_local(self, source_path: Path, source_title: str, rights_note: str) -> int:
        resolved_path = source_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Source file does not exist: {resolved_path}")

        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO video_queue (
                    source_path, source_title, rights_confirmed, rights_note
                )
                VALUES (%s, %s, TRUE, %s)
                RETURNING id
                """,
                (str(resolved_path), source_title.strip(), rights_note.strip()),
            ).fetchone()
        if not row:
            raise RuntimeError("Queue insert returned no job ID")
        return int(row["id"])

    def enqueue_api_job(
        self,
        *,
        source_path: str,
        source_title: str,
        rights_confirmed: bool,
        rights_note: str,
    ) -> int:
        if not source_path:
            raise ValueError("source_path is required")
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO video_queue (
                    source_path, source_title, rights_confirmed, rights_note
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (source_path, source_title.strip(), rights_confirmed, rights_note.strip()),
            ).fetchone()
        if not row:
            raise RuntimeError("Queue insert returned no job ID")
        return int(row["id"])

    def quarantine_unconfirmed(self) -> int:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'quarantined',
                    last_error = 'Publishing rights were not confirmed.'
                WHERE status = 'pending' AND rights_confirmed = FALSE
                """
            )
            return result.rowcount

    def claim_next(self) -> VideoJob | None:
        with self.pool.connection() as conn, conn.transaction():
            row = conn.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM video_queue
                    WHERE status = 'pending'
                      AND rights_confirmed = TRUE
                      AND attempts < %s
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE video_queue AS q
                SET status = 'processing',
                    claimed_at = NOW(),
                    attempts = q.attempts + 1,
                    last_error = NULL
                FROM candidate
                WHERE q.id = candidate.id
                RETURNING q.id, q.source_path, q.source_url, q.source_title,
                          q.rights_confirmed, q.rights_note, q.attempts
                """,
                (self.max_attempts,),
            ).fetchone()
        return VideoJob.model_validate(row) if row else None

    def claim_job(self, job_id: int) -> dict[str, Any] | None:
        with self.pool.connection() as conn, conn.transaction():
            row = conn.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM video_queue
                    WHERE id = %s
                      AND status = 'pending'
                      AND rights_confirmed = TRUE
                      AND attempts < %s
                    FOR UPDATE
                )
                UPDATE video_queue AS q
                SET status = 'processing',
                    claimed_at = NOW(),
                    attempts = q.attempts + 1,
                    last_error = NULL
                FROM candidate
                WHERE q.id = candidate.id
                RETURNING q.id, q.source_path, q.source_url, q.source_title,
                          q.rights_confirmed, q.rights_note, q.status, q.generated_title,
                          q.generated_description, q.generated_tags, q.generated_script,
                          q.output_path, q.youtube_id, q.attempts, q.last_error,
                          q.claimed_at, q.completed_at, q.created_at, q.updated_at
                """,
                (job_id, self.max_attempts),
            ).fetchone()
        return dict(row) if row else None

    def retry_job(self, job_id: int) -> bool:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'pending',
                    last_error = NULL
                WHERE id = %s
                  AND rights_confirmed = TRUE
                  AND status IN ('failed', 'quarantined')
                """,
                (job_id,),
            )
        return bool(result.rowcount)

    def quarantine_job(self, job_id: int) -> bool:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'quarantined'
                WHERE id = %s
                  AND status NOT IN ('uploaded')
                """,
                (job_id,),
            )
        return bool(result.rowcount)

    def mark_rendered(
        self,
        job_id: int,
        content: GeneratedContent,
        output_path: Path,
    ) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                UPDATE video_queue
                SET status = 'rendered',
                    generated_title = %s,
                    generated_description = %s,
                    generated_tags = %s::jsonb,
                    generated_script = %s,
                    output_path = %s
                WHERE id = %s AND status = 'processing'
                """,
                (
                    content.title,
                    content.description,
                    json.dumps(content.tags, ensure_ascii=False),
                    content.script,
                    str(output_path),
                    job_id,
                ),
            )

    def mark_uploaded(self, job_id: int, youtube_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                UPDATE video_queue
                SET status = 'uploaded', youtube_id = %s, completed_at = NOW()
                WHERE id = %s AND status = 'rendered'
                """,
                (youtube_id, job_id),
            )

    def mark_failed(self, job_id: int, error: Exception) -> None:
        safe_error = f"{type(error).__name__}: {error}"[:2000]
        with self.pool.connection() as conn:
            conn.execute(
                """
                UPDATE video_queue
                SET status = CASE WHEN attempts >= %s THEN 'failed' ELSE 'pending' END,
                    last_error = %s
                WHERE id = %s AND status IN ('processing', 'rendered')
                """,
                (self.max_attempts, safe_error, job_id),
            )
