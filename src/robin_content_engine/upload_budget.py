"""Daily upload budget - a ban-safety guard.

YouTube flags channels that dump many auto-generated uploads in a short
window. This module enforces a hard cap on how many videos the pipeline can
publish per calendar day (local date), persisted as work/upload_budget.json.
The cap only gates ACTUAL uploads; processing/packaging still runs so the
package is ready for the next allowed day.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import Settings

_BUDGET_FILENAME = "upload_budget.json"


def _budget_path(settings: Settings) -> Path:
    return settings.work_dir / _BUDGET_FILENAME


def _load(settings: Settings) -> dict[str, object]:
    path = _budget_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save(settings: Settings, payload: dict[str, object]) -> None:
    path = _budget_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def daily_uploads_used(settings: Settings) -> int:
    payload = _load(settings)
    if payload.get("date") != date.today().isoformat():
        return 0
    count = payload.get("count", 0)
    # The JSON file is written by this module with an integer count, so a
    # stored value of any other shape is corrupt/malformed data - reject it
    # (bool is explicitly rejected because bool subclasses int) rather than
    # coercing an object into an int, which could never be a valid count.
    if isinstance(count, bool) or not isinstance(count, (int, float, str)):
        return 0
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


def upload_allowed(settings: Settings) -> bool:
    """True when today's upload count is below the configured daily cap."""
    return daily_uploads_used(settings) < settings.youtube_max_uploads_per_day


def record_upload(settings: Settings) -> int:
    """Increment today's upload count and return the new count. Never
    raises - a budget bookkeeping failure must not fail an upload."""
    try:
        count = daily_uploads_used(settings) + 1
        _save(settings, {"date": date.today().isoformat(), "count": count})
        return count
    except Exception:
        return 0


def upload_budget_summary(settings: Settings) -> str:
    used = daily_uploads_used(settings)
    cap = settings.youtube_max_uploads_per_day
    if used >= cap:
        return f"Daily upload cap reached ({used}/{cap}) - new uploads resume tomorrow."
    return f"Daily uploads: {used}/{cap} used."
