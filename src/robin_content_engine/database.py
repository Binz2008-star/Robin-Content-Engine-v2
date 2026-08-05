import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
