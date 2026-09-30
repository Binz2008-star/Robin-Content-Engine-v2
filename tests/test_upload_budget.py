from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine.upload_budget import (  # noqa: E402
    daily_uploads_used,
    record_upload,
    upload_allowed,
    upload_budget_summary,
)


def _settings(tmp_path: Path, cap: int = 4) -> SimpleNamespace:
    return SimpleNamespace(work_dir=tmp_path, youtube_max_uploads_per_day=cap)


def test_budget_starts_at_zero(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert daily_uploads_used(s) == 0
    assert upload_allowed(s) is True
    assert "0/4" in upload_budget_summary(s)


def test_record_upload_increments_and_caps(tmp_path: Path) -> None:
    s = _settings(tmp_path, cap=2)
    assert record_upload(s) == 1
    assert record_upload(s) == 2
    assert upload_allowed(s) is False
    assert "reached" in upload_budget_summary(s)


def test_budget_resets_next_day(tmp_path: Path) -> None:
    s = _settings(tmp_path, cap=2)
    record_upload(s)
    record_upload(s)
    assert upload_allowed(s) is False
    # Simulate the next calendar day by rewriting the state date.
    from datetime import date, timedelta

    payload_path = tmp_path / "upload_budget.json"
    payload = __import__("json").loads(payload_path.read_text(encoding="utf-8"))
    payload["date"] = (date.today() + timedelta(days=1)).isoformat()
    payload_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    assert daily_uploads_used(s) == 0
    assert upload_allowed(s) is True


def _write_budget(tmp_path: Path, payload: dict[str, object]) -> None:
    from datetime import date

    state = {"date": date.today().isoformat(), **payload}
    (tmp_path / "upload_budget.json").write_text(
        __import__("json").dumps(state), encoding="utf-8"
    )


def test_count_parsing_accepts_int_float_and_numeric_string(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _write_budget(tmp_path, {"count": 3})
    assert daily_uploads_used(s) == 3
    _write_budget(tmp_path, {"count": "2"})
    assert daily_uploads_used(s) == 2
    _write_budget(tmp_path, {"count": 2.5})
    assert daily_uploads_used(s) == 2


def test_count_parsing_rejects_bool_and_non_numeric_values(tmp_path: Path) -> None:
    # bool is rejected explicitly (bool subclasses int, so it would otherwise
    # coerce to 1); dict/list/None/empty-string are corrupt state, not counts.
    for corrupt in (True, False, {"n": 1}, [3], None, "not-a-number"):
        s = _settings(tmp_path)
        _write_budget(tmp_path, {"count": corrupt})
        assert daily_uploads_used(s) == 0, f"count {corrupt!r} must read as 0"


# ---------------------------------------------------------------------------
# DB-backed budget (cloud runner)
# ---------------------------------------------------------------------------


def test_db_uploads_today_is_read_only_and_timezone_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    import robin_content_engine.upload_budget as ub

    executed: list[tuple[str, object]] = []

    class Conn:
        def __enter__(self) -> Conn:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def execute(self, sql: str, params: object = None) -> Conn:
            executed.append((sql, params))
            return self

        def fetchone(self) -> tuple[int]:
            return (2,)

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda url: Conn())

    assert ub.db_uploads_today("db") == 2
    sql, params = executed[0]
    assert sql.strip().upper().startswith("SELECT")
    assert "status = 'uploaded'" in sql
    assert params == ("Asia/Dubai", "Asia/Dubai")


def test_db_upload_allowed_compares_with_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import robin_content_engine.upload_budget as ub

    monkeypatch.setattr(ub, "db_uploads_today", lambda url, timezone="Asia/Dubai": 2)

    assert not ub.db_upload_allowed(
        SimpleNamespace(database_url="db", youtube_max_uploads_per_day=2)  # type: ignore[arg-type]
    )
    assert ub.db_upload_allowed(
        SimpleNamespace(database_url="db", youtube_max_uploads_per_day=3)  # type: ignore[arg-type]
    )
