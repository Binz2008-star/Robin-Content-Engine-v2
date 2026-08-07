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

from robin_content_engine.database import JobRepository, _rows_to_dicts  # noqa: E402


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
