from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
