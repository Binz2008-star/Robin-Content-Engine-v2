"""Opt-in integration tests against a REAL PostgreSQL database.

These tests exercise the psycopg SQL in database.py the way the fake-pool
unit tests cannot: real CHECK constraints, FOR UPDATE SKIP LOCKED
semantics, the set_updated_at trigger, and the trigger that refreshes
updated_at on every UPDATE.

They are deliberately NOT part of the default run: they require a
disposable PostgreSQL instance you control. Point them at one with:

    $env:ROBIN_TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/postgres"
    python -m pytest tests/test_database_integration.py

Everything runs inside a throwaway schema (robin_it_<random>), which is
dropped (CASCADE) when the module finishes - your other tables and data
are never touched.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from robin_content_engine.database import AUTO_QUARANTINE_REASON, JobRepository

TEST_DATABASE_URL = os.environ.get("ROBIN_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set ROBIN_TEST_DATABASE_URL to a disposable Postgres to run integration tests",
)

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schema.sql"


@pytest.fixture(scope="module")
def test_database_url() -> Iterator[str]:
    """Create a throwaway schema, apply schema.sql inside it, and drop the
    schema again at teardown. All tests in this module share it."""
    assert TEST_DATABASE_URL is not None
    schema_name = f"robin_it_{secrets.token_hex(4)}"
    admin_pool = ConnectionPool(
        conninfo=TEST_DATABASE_URL, min_size=1, max_size=1, open=False
    )
    admin_pool.open(wait=True)
    try:
        with admin_pool.connection() as conn:
            conn.execute(f'CREATE SCHEMA "{schema_name}"')
            conn.execute(f'SET search_path TO "{schema_name}"')
            conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    finally:
        admin_pool.close()

    from urllib.parse import quote

    options = quote(f"-csearch_path={schema_name}")
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    yield f"{TEST_DATABASE_URL}{separator}options={options}"

    admin_pool = ConnectionPool(
        conninfo=TEST_DATABASE_URL, min_size=1, max_size=1, open=False
    )
    admin_pool.open(wait=True)
    try:
        with admin_pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
    finally:
        admin_pool.close()


@pytest.fixture(autouse=True)
def _clean_tables(test_database_url: str) -> Iterator[None]:
    yield
    cleanup_pool = ConnectionPool(
        conninfo=test_database_url, min_size=1, max_size=1, open=False
    )
    cleanup_pool.open(wait=True)
    try:
        with cleanup_pool.connection() as conn:
            conn.execute("TRUNCATE youtube_videos, youtube_channels, video_queue")
    finally:
        cleanup_pool.close()


@pytest.fixture()
def repo(test_database_url: str) -> Iterator[JobRepository]:
    with JobRepository(test_database_url, max_attempts=3).running() as repository:
        yield repository


def _insert_job(
    test_database_url: str,
    *,
    source_title: str = "integration source",
    rights_confirmed: bool = True,
) -> int:
    pool = ConnectionPool(conninfo=test_database_url, min_size=1, max_size=1, open=False)
    pool.open(wait=True)
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO video_queue (source_path, source_title, rights_confirmed)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (f"/tmp/{secrets.token_hex(4)}.mp4", source_title, rights_confirmed),
            ).fetchone()
            assert row is not None
            return int(row[0])
    finally:
        pool.close()


def test_mark_deterministic_failure_quarantines_pending_row(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)

    assert repo.mark_deterministic_failure(job_id, "deterministic: bad source audio") is True

    job = repo.get_job(job_id)
    assert job is not None
    assert job["status"] == "quarantined"
    assert job["last_error"] == "deterministic: bad source audio"
    assert job["claimed_at"] is None


def test_mark_deterministic_failure_truncates_reason_to_2000_chars(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)
    long_reason = "x" * 5000

    assert repo.mark_deterministic_failure(job_id, long_reason) is True

    job = repo.get_job(job_id)
    assert job is not None
    assert job["last_error"] == "x" * 2000


def test_mark_deterministic_failure_clears_claimed_at_of_in_flight_job(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)
    claimed = repo.claim_next()
    assert claimed is not None and claimed.id == job_id

    assert repo.mark_deterministic_failure(job_id, "hung encode") is True

    job = repo.get_job(job_id)
    assert job is not None
    assert job["status"] == "quarantined"
    assert job["claimed_at"] is None


def test_mark_deterministic_failure_never_overwrites_operator_decision(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)
    repo.claim_next()
    repo.quarantine_job(job_id)

    # job is no longer 'pending' - the operator decision must win
    assert repo.mark_deterministic_failure(job_id, "late failure") is False

    job = repo.get_job(job_id)
    assert job is not None
    assert job["status"] == "quarantined"
    assert job["last_error"] == "Quarantined by operator."


def test_claim_next_skips_locked_rows_under_concurrency(
    repo: JobRepository, test_database_url: str
) -> None:
    first_id = _insert_job(test_database_url, source_title="first")
    second_id = _insert_job(test_database_url, source_title="second")

    # a second live pool simulating a second worker
    with JobRepository(test_database_url, max_attempts=3).running() as second:
        claimed_by_repo = repo.claim_next()
        claimed_by_second = second.claim_next()

    assert claimed_by_repo is not None
    assert claimed_by_second is not None
    assert {claimed_by_repo.id, claimed_by_second.id} == {first_id, second_id}

    statuses = {job["id"]: job["status"] for job in repo.list_jobs()}
    assert statuses == {first_id: "processing", second_id: "processing"}


def test_mark_failed_exhausts_attempts_before_retryable(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)

    for _ in range(repo.max_attempts):
        claimed = repo.claim_next()
        assert claimed is not None and claimed.id == job_id
        repo.mark_failed(job_id, ValueError("transient"))
        job = repo.get_job(job_id)
        assert job is not None
        assert job["status"] == "pending"
        assert job["last_error"] == "ValueError: transient"

    assert repo.claim_next() is None
    job = repo.get_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["completed_at"] is not None

    # a failed job is retryable by the operator...
    assert repo.retry_job(job_id) is True
    assert repo.claim_next() is not None


def test_rights_lifecycle_against_real_constraints(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url, rights_confirmed=False)

    assert repo.approve_rights(job_id, "verified on phone") is not None
    job = repo.get_job(job_id)
    assert job is not None
    assert job["rights_confirmed"] is True
    assert job["status"] == "pending"
    assert "verified on phone" in job["rights_note"]

    # rejecting an already-confirmed job is a safe no-op
    assert repo.reject_rights(job_id, "nope") is None
    assert repo.quarantine_unconfirmed() == 0

    # auto-quarantine only hits pending/unconfirmed rows
    job_id2 = _insert_job(test_database_url, source_title="unconfirmed", rights_confirmed=False)
    assert repo.quarantine_unconfirmed() == 1
    job2 = repo.get_job(job_id2)
    assert job2 is not None
    assert job2["status"] == "quarantined"
    assert job2["last_error"] == AUTO_QUARANTINE_REASON
    assert [j["id"] for j in repo.list_pending_rights_review()] == [job_id2]


def test_updated_at_trigger_refreshes_on_update(
    repo: JobRepository, test_database_url: str
) -> None:
    job_id = _insert_job(test_database_url)
    before = repo.get_job(job_id)
    assert before is not None
    assert before["updated_at"] is not None

    repo.quarantine_job(job_id)
    after = repo.get_job(job_id)
    assert after is not None
    assert after["status"] == "quarantined"
    assert after["updated_at"] > before["updated_at"]