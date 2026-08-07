from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.database import (  # noqa: E402
    AUTO_QUARANTINE_REASON,
    JobRepository,
    _rows_to_dicts,
)


@dataclass
class FakeResult:
    description: list[tuple[str, ...]] | None
    rows: list[tuple[Any, ...]]
    rowcount: int = 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


@dataclass
class FakeConnection:
    result: FakeResult
    executed: list[tuple[str, Any]] = field(default_factory=list)

    def execute(self, sql: str, params: Any = None) -> FakeResult:
        self.executed.append((sql, params))
        return self.result

    @contextmanager
    def transaction(self):
        yield


class FakePool:
    def __init__(self, result: FakeResult) -> None:
        self.conn = FakeConnection(result)

    @contextmanager
    def connection(self):
        yield self.conn


def _repo_with_fake_pool(result: FakeResult) -> tuple[JobRepository, FakeConnection]:
    repo = JobRepository("postgresql://fake", 3)
    pool = FakePool(result)
    repo.pool = pool  # type: ignore[assignment]
    return repo, pool.conn


def test_rows_to_dicts_uses_real_description() -> None:
    description = [("status",), ("count",)]
    rows = [("pending", 2)]
    assert _rows_to_dicts(rows, description) == [{"status": "pending", "count": 2}]


def test_status_counts_uses_real_cursor_description_not_none() -> None:
    # Regression test: status_counts() used to pass a literal `None` as the
    # cursor description to _rows_to_dicts, which produced empty dicts and
    # raised KeyError on `row["status"]`. It must use the real
    # result.description returned by conn.execute().
    description = [("status",), ("count",)]
    rows = [("pending", 2), ("failed", 1)]
    repo, _ = _repo_with_fake_pool(FakeResult(description=description, rows=rows))

    counts = repo.status_counts()

    assert counts == {
        "pending": 2,
        "processing": 0,
        "rendered": 0,
        "uploaded": 0,
        "failed": 1,
        "quarantined": 0,
        "total": 3,
    }


def test_retry_job_sql_clears_lifecycle_fields_and_restricts_states() -> None:
    repo, conn = _repo_with_fake_pool(FakeResult(description=None, rows=[], rowcount=1))

    ok = repo.retry_job(42)

    assert ok is True
    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "status = 'pending'" in normalized
    assert "last_error = NULL" in normalized
    assert "claimed_at = NULL" in normalized
    assert "completed_at = NULL" in normalized
    assert "status IN ('failed', 'quarantined')" in normalized
    assert "rights_confirmed = TRUE" in normalized
    assert params == (42,)


def test_retry_job_returns_false_when_no_row_updated() -> None:
    repo, _ = _repo_with_fake_pool(FakeResult(description=None, rows=[], rowcount=0))
    assert repo.retry_job(1) is False


def test_quarantine_job_sql_restricts_valid_states_and_sets_reason() -> None:
    repo, conn = _repo_with_fake_pool(FakeResult(description=None, rows=[], rowcount=1))

    ok = repo.quarantine_job(7)

    assert ok is True
    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "status = 'quarantined'" in normalized
    assert "last_error = 'Quarantined by operator.'" in normalized
    assert "status IN ('pending', 'processing', 'rendered', 'failed')" in normalized
    assert "uploaded" not in normalized
    assert params == (7,)


def test_quarantine_job_returns_false_when_no_row_updated() -> None:
    repo, _ = _repo_with_fake_pool(FakeResult(description=None, rows=[], rowcount=0))
    assert repo.quarantine_job(1) is False


def _rights_review_row(**overrides: Any) -> tuple[Any, ...]:
    base = {
        "id": 6,
        "source_path": "/captures/clip.mp4",
        "source_url": None,
        "source_title": "clip",
        "rights_confirmed": True,
        "rights_note": (
            "Discovered from configured local capture directory."
            "\n\nOperator verification: confirmed"
        ),
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
        "created_at": "2026-08-08T00:00:00Z",
        "updated_at": "2026-08-08T00:00:00Z",
    }
    base.update(overrides)
    return tuple(base.values())


_REVIEW_DESCRIPTION = [
    ("id",), ("source_path",), ("source_url",), ("source_title",), ("rights_confirmed",),
    ("rights_note",), ("status",), ("generated_title",), ("generated_description",),
    ("generated_tags",), ("generated_script",), ("output_path",), ("youtube_id",),
    ("attempts",), ("last_error",), ("claimed_at",), ("completed_at",), ("created_at",),
    ("updated_at",),
]


def test_list_pending_rights_review_sql_scopes_to_unconfirmed_pending_or_auto_quarantined() -> (
    None
):
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[]))

    repo.list_pending_rights_review()

    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "WHERE rights_confirmed = FALSE" in normalized
    assert "status = 'pending'" in normalized
    assert "OR (status = 'quarantined' AND last_error = %s)" in normalized
    assert "ORDER BY created_at, id" in normalized
    assert params == (AUTO_QUARANTINE_REASON,)


def test_approve_rights_sql_is_atomic_conditional_update() -> None:
    row = _rights_review_row()
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[row]))

    result = repo.approve_rights(6, "confirmed by operator")

    assert result is not None
    assert result["rights_confirmed"] is True
    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "SET rights_confirmed = TRUE" in normalized
    assert "status = 'pending'" in normalized
    assert "last_error = NULL" in normalized
    assert "rights_note = COALESCE(rights_note, '') || %s" in normalized
    assert "WHERE id = %s" in normalized
    assert "AND rights_confirmed = FALSE" in normalized
    assert "status = 'pending' OR (status = 'quarantined' AND last_error = %s)" in normalized
    assert "RETURNING" in normalized
    assert params == (
        "\n\nOperator verification: confirmed by operator",
        6,
        AUTO_QUARANTINE_REASON,
    )


def test_approve_rights_allows_auto_quarantined_unconfirmed() -> None:
    row = _rights_review_row(status="quarantined", last_error=None)
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[row]))

    result = repo.approve_rights(6, "confirmed after auto-quarantine")

    assert result is not None
    _, params = conn.executed[-1]
    assert params[-1] == AUTO_QUARANTINE_REASON


def test_approve_rights_returns_none_on_conflict() -> None:
    repo, _ = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[]))
    assert repo.approve_rights(6, "confirmed") is None


def test_approve_rights_rejects_empty_note() -> None:
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[]))
    with pytest.raises(ValueError, match="must not be empty"):
        repo.approve_rights(6, "   ")
    assert conn.executed == []


def test_reject_rights_sql_is_atomic_conditional_update() -> None:
    row = _rights_review_row(
        rights_confirmed=False, status="quarantined", last_error="Rights rejected by operator."
    )
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[row]))

    result = repo.reject_rights(6, "not owned by operator")

    assert result is not None
    assert result["rights_confirmed"] is False
    assert result["status"] == "quarantined"
    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "SET status = 'quarantined'" in normalized
    assert "last_error = 'Rights rejected by operator.'" in normalized
    assert "rights_note = COALESCE(rights_note, '') || %s" in normalized
    assert "AND rights_confirmed = FALSE" in normalized
    assert "status = 'pending' OR (status = 'quarantined' AND last_error = %s)" in normalized
    assert params == ("\n\nOperator rejection: not owned by operator", 6, AUTO_QUARANTINE_REASON)


def test_reject_rights_allows_auto_quarantined_unconfirmed() -> None:
    row = _rights_review_row(status="quarantined", last_error="Rights rejected by operator.")
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[row]))

    result = repo.reject_rights(6, "not owned")

    assert result is not None
    _, params = conn.executed[-1]
    assert params[-1] == AUTO_QUARANTINE_REASON


def test_reject_rights_returns_none_on_conflict() -> None:
    repo, _ = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[]))
    assert repo.reject_rights(6, "reason") is None


def test_reject_rights_rejects_empty_reason() -> None:
    repo, conn = _repo_with_fake_pool(FakeResult(description=_REVIEW_DESCRIPTION, rows=[]))
    with pytest.raises(ValueError, match="must not be empty"):
        repo.reject_rights(6, "")
    assert conn.executed == []


def test_quarantine_unconfirmed_sql_uses_auto_quarantine_reason_constant() -> None:
    repo, conn = _repo_with_fake_pool(FakeResult(description=None, rows=[], rowcount=1))

    repo.quarantine_unconfirmed()

    sql, params = conn.executed[-1]
    normalized = " ".join(sql.split())
    assert "SET status = 'quarantined'" in normalized
    assert "last_error = %s" in normalized
    assert "WHERE status = 'pending' AND rights_confirmed = FALSE" in normalized
    assert params == (AUTO_QUARANTINE_REASON,)
