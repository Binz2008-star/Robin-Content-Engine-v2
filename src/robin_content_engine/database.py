import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeAlias, cast

from psycopg_pool import ConnectionPool

from .models import GeneratedContent, VideoJob

RowDict: TypeAlias = dict[str, Any]

# Reason text set by quarantine_unconfirmed() when it auto-quarantines a
# pending-but-unconfirmed job before it can be claimed. Jobs in this exact
# state are a safety side effect, not an operator decision, so the rights
# review flow must still treat them as reviewable. Any other quarantined
# state (e.g. explicit operator rejection) must not match this marker.
AUTO_QUARANTINE_REASON = "Publishing rights were not confirmed."


def _row_to_dict(row: tuple[Any, ...] | None, description: Any) -> RowDict | None:
    if row is None:
        return None
    columns = [column[0] for column in description or []]
    return cast(RowDict, dict(zip(columns, row, strict=True)))


def _rows_to_dicts(rows: list[tuple[Any, ...]], description: Any) -> list[RowDict]:
    columns = [column[0] for column in description or []]
    return [cast(RowDict, dict(zip(columns, row, strict=True))) for row in rows]


class JobRepository:
    def __init__(self, database_url: str, max_attempts: int, pool_min_size: int = 1, pool_max_size: int = 5) -> None:
        self.max_attempts = max_attempts
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=pool_min_size,
            max_size=pool_max_size,
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

    def list_jobs(self) -> list[RowDict]:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                SELECT id, source_path, source_url, source_title, rights_confirmed,
                       rights_note, status, generated_title, generated_description,
                       generated_tags, generated_script, output_path, youtube_id,
                       attempts, last_error, claimed_at, completed_at, created_at,
                       updated_at
                FROM video_queue
                ORDER BY created_at DESC, id DESC
                """
            )
            rows = result.fetchall()
        return _rows_to_dicts(rows, result.description)

    def get_job(self, job_id: int) -> RowDict | None:
        with self.pool.connection() as conn:
            result = conn.execute(
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
            )
            row = result.fetchone()
        return _row_to_dict(row, result.description)

    def status_counts(self) -> dict[str, int]:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM video_queue
                GROUP BY status
                """
            )
            rows = result.fetchall()
            description = result.description
        counts = {
            "pending": 0,
            "processing": 0,
            "rendered": 0,
            "uploaded": 0,
            "failed": 0,
            "quarantined": 0,
            "total": 0,
        }
        row_dicts = _rows_to_dicts(rows, description)
        for row in row_dicts:
            status = str(row["status"])
            count = int(row["count"])
            counts[status] = count
            counts["total"] += count
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
        return int(row[0])

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
        return int(row[0])

    def quarantine_unconfirmed(self) -> int:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'quarantined',
                    last_error = %s
                WHERE status = 'pending' AND rights_confirmed = FALSE
                """,
                (AUTO_QUARANTINE_REASON,),
            )
            return result.rowcount

    def claim_next(self) -> VideoJob | None:
        with self.pool.connection() as conn, conn.transaction():
            result = conn.execute(
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
            )
            row = result.fetchone()
        return VideoJob.model_validate(_row_to_dict(row, result.description)) if row else None

    def claim_job(self, job_id: int) -> RowDict | None:
        with self.pool.connection() as conn, conn.transaction():
            result = conn.execute(
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
            )
            row = result.fetchone()
        return _row_to_dict(row, result.description)

    def retry_job(self, job_id: int) -> bool:
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'pending',
                    last_error = NULL,
                    claimed_at = NULL,
                    completed_at = NULL
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
                SET status = 'quarantined',
                    last_error = 'Quarantined by operator.'
                WHERE id = %s
                  AND status IN ('pending', 'processing', 'rendered', 'failed')
                """,
                (job_id,),
            )
        return bool(result.rowcount)

    def list_pending_rights_review(self) -> list[RowDict]:
        """Sources still awaiting explicit operator rights verification.

        Includes both jobs never reviewed yet (pending/unconfirmed) and
        jobs auto-quarantined by quarantine_unconfirmed() before an
        operator could review them - that auto-quarantine is a safety
        side effect of run_once(), not an operator decision, so it must
        stay reviewable. Explicitly operator-rejected jobs are excluded:
        they carry a different last_error and must not resurface here.
        """
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                SELECT id, source_path, source_url, source_title, rights_confirmed,
                       rights_note, status, generated_title, generated_description,
                       generated_tags, generated_script, output_path, youtube_id,
                       attempts, last_error, claimed_at, completed_at, created_at,
                       updated_at
                FROM video_queue
                WHERE rights_confirmed = FALSE
                  AND (
                    status = 'pending'
                    OR (status = 'quarantined' AND last_error = %s)
                  )
                ORDER BY created_at, id
                """,
                (AUTO_QUARANTINE_REASON,),
            )
            rows = result.fetchall()
        return _rows_to_dicts(rows, result.description)

    def approve_rights(self, job_id: int, verification_note: str) -> RowDict | None:
        """Explicitly confirm publishing rights for one reviewable source.

        Only mutates a job that is either pending/unconfirmed or was
        auto-quarantined by quarantine_unconfirmed() while still
        unconfirmed (an atomic conditional UPDATE, not read-then-write) -
        already-confirmed, operator-rejected, in-progress, or terminal
        jobs are left untouched and this returns None as a safe conflict
        signal. Never claims, renders, or uploads; status is (re)set to
        'pending' so the existing queue rules pick it up normally, and
        the auto-quarantine last_error is cleared. The rights_note is
        appended to, never overwritten, so discovery provenance is
        preserved.
        """
        cleaned_note = verification_note.strip()
        if not cleaned_note:
            raise ValueError("verification_note must not be empty")
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET rights_confirmed = TRUE,
                    status = 'pending',
                    last_error = NULL,
                    rights_note = COALESCE(rights_note, '') || %s
                WHERE id = %s
                  AND rights_confirmed = FALSE
                  AND (
                    status = 'pending'
                    OR (status = 'quarantined' AND last_error = %s)
                  )
                RETURNING id, source_path, source_url, source_title, rights_confirmed,
                          rights_note, status, generated_title, generated_description,
                          generated_tags, generated_script, output_path, youtube_id,
                          attempts, last_error, claimed_at, completed_at, created_at,
                          updated_at
                """,
                (f"\n\nOperator verification: {cleaned_note}", job_id, AUTO_QUARANTINE_REASON),
            )
            row = result.fetchone()
        return _row_to_dict(row, result.description)

    def reject_rights(self, job_id: int, reason: str) -> RowDict | None:
        """Reject one reviewable source. rights_confirmed stays FALSE; the
        job is quarantined (existing status value, no schema change) so it
        is excluded from claim_next()/claim_job(). The source row and file
        are never deleted - only jobs pending/unconfirmed or auto-
        quarantined/unconfirmed can be rejected via this atomic
        conditional UPDATE (not read-then-write); already-confirmed,
        operator-rejected, in-progress, or terminal jobs return None as a
        safe conflict signal, so an already-rejected job cannot be
        rejected again or otherwise silently mutated.
        """
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("reason must not be empty")
        with self.pool.connection() as conn:
            result = conn.execute(
                """
                UPDATE video_queue
                SET status = 'quarantined',
                    last_error = 'Rights rejected by operator.',
                    rights_note = COALESCE(rights_note, '') || %s
                WHERE id = %s
                  AND rights_confirmed = FALSE
                  AND (
                    status = 'pending'
                    OR (status = 'quarantined' AND last_error = %s)
                  )
                RETURNING id, source_path, source_url, source_title, rights_confirmed,
                          rights_note, status, generated_title, generated_description,
                          generated_tags, generated_script, output_path, youtube_id,
                          attempts, last_error, claimed_at, completed_at, created_at,
                          updated_at
                """,
                (f"\n\nOperator rejection: {cleaned_reason}", job_id, AUTO_QUARANTINE_REASON),
            )
            row = result.fetchone()
        return _row_to_dict(row, result.description)

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
