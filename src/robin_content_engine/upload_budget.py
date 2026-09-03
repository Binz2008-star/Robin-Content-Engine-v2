"""Daily upload budget - a ban-safety guard.

YouTube flags channels that dump many auto-generated uploads in a short
window. This module enforces a hard cap on how many videos the pipeline can
publish per calendar day (local date), persisted as work/upload_budget.json.
The cap only gates ACTUAL uploads; processing/packaging still runs so the
package is ready for the next allowed day.
"""

from __future__ import annotations

import json
from datetime import date, datetime
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
    try:
        return int(payload.get("count", 0))
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


# --- New day-aware budget functions ---

def load_budget(settings: Settings) -> dict[str, object]:
    """Load budget from work/upload_budget.json. Auto-resets if new calendar
    day: if the stored date differs from today, daily_count resets to 0 and
    last_reset_utc is updated. Returns a dict with keys 'daily_count',
    'last_reset_utc', 'date', 'cap'. """
    path = _budget_path(settings)
    now = datetime.utcnow()
    payload = _load(settings)
    stored_date = payload.get("date")
    if stored_date != date.today().isoformat():
        # New day — reset counter, keep historical record
        payload["daily_count"] = 0
        payload["last_reset_utc"] = now.isoformat()
        payload["date"] = now.date().isoformat()
    payload.setdefault("cap", settings.youtube_max_uploads_per_day)
    return payload


def increment_and_check(cap: int | None = None) -> tuple[bool, str]:
    """Increment today's upload count and return (allowed, message).

    If daily cap is reached, allowed=False and message explains the situation.
    The budget file is only written when a new upload is recorded.
    """
    from .config import Settings as _Settings
    settings = _Settings() if cap is None else _Settings(youtube_max_uploads_per_day=cap)
    budget = load_budget(settings)
    used = budget.get("daily_count", 0)
    if cap is None:
        cap = budget.get("cap", settings.youtube_max_uploads_per_day)
    if used >= cap:
        reset_date = budget.get("last_reset_utc", "")
        reset_local = (
            datetime.fromisoformat(reset_date).strftime("%Y-%m-%d")
            if reset_date
            else "tomorrow"
        )
        allowed = False
        message = (
            f"Daily cap reached ({used}/{cap}) - new uploads resume {reset_local}."
        )
    else:
        budget["daily_count"] = used + 1
        _save(settings, budget)
        allowed = True
        message = f"Upload {used + 1}/{cap} recorded. Resets {datetime.now().strftime('%Y-%m-%d')}."
    return allowed, message