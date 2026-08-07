from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from robin_content_engine import cli as cli_module  # noqa: E402
from robin_content_engine.cli import app as cli_app  # noqa: E402

DISCOVERY_NOTE = "Discovered from configured local capture directory."
SECRET_SENTINEL = "sk-do-not-print-this-secret"


class FakeRepository:
    """In-memory double implementing exactly the JobRepository methods the
    rights-* CLI commands use, mirroring the real atomic-conditional-update
    semantics (approve/reject only succeed from pending+unconfirmed)."""

    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self.next_id = 1

    @contextmanager
    def running(self):
        yield self

    def seed(
        self,
        *,
        status: str = "pending",
        rights_confirmed: bool = False,
        rights_note: str = DISCOVERY_NOTE,
        source_title: str = "clip",
        source_path: str = "/captures/clip.mp4",
    ) -> int:
        job_id = self.next_id
        self.next_id += 1
        self.jobs[job_id] = {
            "id": job_id,
            "source_path": source_path,
            "source_title": source_title,
            "status": status,
            "rights_confirmed": rights_confirmed,
            "rights_note": rights_note,
            "last_error": None,
        }
        return job_id

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(job) for job in sorted(self.jobs.values(), key=lambda j: -j["id"])]

    def list_pending_rights_review(self) -> list[dict[str, Any]]:
        return [
            dict(job)
            for job in sorted(self.jobs.values(), key=lambda j: j["id"])
            if job["status"] == "pending" and job["rights_confirmed"] is False
        ]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return dict(job) if job else None

    def approve_rights(self, job_id: int, verification_note: str) -> dict[str, Any] | None:
        note = verification_note.strip()
        if not note:
            raise ValueError("verification_note must not be empty")
        job = self.jobs.get(job_id)
        if job is None or job["status"] != "pending" or job["rights_confirmed"] is not False:
            return None
        job["rights_confirmed"] = True
        job["rights_note"] = f"{job['rights_note']}\n\nOperator verification: {note}"
        return dict(job)

    def reject_rights(self, job_id: int, reason: str) -> dict[str, Any] | None:
        cleaned = reason.strip()
        if not cleaned:
            raise ValueError("reason must not be empty")
        job = self.jobs.get(job_id)
        if job is None or job["status"] != "pending" or job["rights_confirmed"] is not False:
            return None
        job["status"] = "quarantined"
        job["last_error"] = "Rights rejected by operator."
        job["rights_note"] = f"{job['rights_note']}\n\nOperator rejection: {cleaned}"
        return dict(job)


class FakeSettings:
    def __init__(self) -> None:
        self.database_url = f"postgresql://user:{SECRET_SENTINEL}@fake-host/db"
        self.max_job_attempts = 3


def _patch(monkeypatch: pytest.MonkeyPatch, repo: FakeRepository) -> None:
    monkeypatch.setattr(cli_module, "Settings", FakeSettings)
    monkeypatch.setattr(cli_module, "JobRepository", lambda *a, **kw: repo)


# ---------------------------------------------------------------------------
# 1-2: rights-list
# ---------------------------------------------------------------------------


def test_unconfirmed_pending_job_appears_in_review_list(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.seed(source_title="Fortnite clip")
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-list"])

    assert result.exit_code == 0, result.output
    assert "Fortnite clip" in result.output


def test_confirmed_job_not_shown_in_default_pending_rights_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    repo.seed(source_title="Already confirmed", rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-list"])

    assert result.exit_code == 0, result.output
    assert "No jobs awaiting rights review." in result.output
    assert "Already confirmed" not in result.output

    all_result = CliRunner().invoke(cli_app, ["rights-list", "--all"])
    assert "Already confirmed" in all_result.output


# ---------------------------------------------------------------------------
# 3-8: rights-approve
# ---------------------------------------------------------------------------


def test_approve_requires_explicit_non_empty_note(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-approve", str(job_id), "--note", "   "])

    assert result.exit_code != 0
    assert repo.jobs[job_id]["rights_confirmed"] is False


def test_approve_requires_note_option_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-approve", str(job_id)])

    assert result.exit_code != 0


def test_approve_changes_rights_confirmed_false_to_true(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(
        cli_app, ["rights-approve", str(job_id), "--note", "confirmed personally recorded"]
    )

    assert result.exit_code == 0, result.output
    assert repo.jobs[job_id]["rights_confirmed"] is True
    assert repo.jobs[job_id]["status"] == "pending"


def test_approve_preserves_discovery_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed(rights_note=DISCOVERY_NOTE)
    _patch(monkeypatch, repo)

    CliRunner().invoke(cli_app, ["rights-approve", str(job_id), "--note", "verified"])

    final_note = repo.jobs[job_id]["rights_note"]
    assert DISCOVERY_NOTE in final_note
    assert "Operator verification: verified" in final_note


def test_approve_does_not_change_source_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original-bytes-do-not-touch")
    repo = FakeRepository()
    job_id = repo.seed(source_path=str(source))
    _patch(monkeypatch, repo)

    CliRunner().invoke(cli_app, ["rights-approve", str(job_id), "--note", "verified"])

    assert source.read_bytes() == b"original-bytes-do-not-touch"


def test_approve_never_constructs_content_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    # ContentEngine is the single gate in front of both render and upload in
    # this codebase (see pipeline.ContentEngine._process); asserting it is
    # never constructed proves approve triggers neither.
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    def exploding_content_engine(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("rights-approve must never construct ContentEngine")

    monkeypatch.setattr(cli_module, "ContentEngine", exploding_content_engine)

    result = CliRunner().invoke(
        cli_app, ["rights-approve", str(job_id), "--note", "verified"]
    )

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 9-11: rights-reject
# ---------------------------------------------------------------------------


def test_reject_keeps_rights_confirmed_false(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(
        cli_app, ["rights-reject", str(job_id), "--note", "not personally owned"]
    )

    assert result.exit_code == 0, result.output
    assert repo.jobs[job_id]["rights_confirmed"] is False
    assert repo.jobs[job_id]["status"] == "quarantined"


def test_reject_requires_non_empty_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-reject", str(job_id), "--note", ""])

    assert result.exit_code != 0
    assert repo.jobs[job_id]["status"] == "pending"


def test_rejected_source_removed_from_default_review_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    job_id = repo.seed(source_title="Rejected clip")
    _patch(monkeypatch, repo)

    CliRunner().invoke(cli_app, ["rights-reject", str(job_id), "--note", "not owned"])
    result = CliRunner().invoke(cli_app, ["rights-list"])

    assert "Rejected clip" not in result.output


def test_reject_never_constructs_content_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    def exploding_content_engine(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("rights-reject must never construct ContentEngine")

    monkeypatch.setattr(cli_module, "ContentEngine", exploding_content_engine)

    result = CliRunner().invoke(cli_app, ["rights-reject", str(job_id), "--note", "not owned"])

    assert result.exit_code == 0, result.output


def test_reject_does_not_delete_source_file_or_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"keep-me")
    repo = FakeRepository()
    job_id = repo.seed(source_path=str(source))
    _patch(monkeypatch, repo)

    CliRunner().invoke(cli_app, ["rights-reject", str(job_id), "--note", "not owned"])

    assert source.is_file()
    assert job_id in repo.jobs


# ---------------------------------------------------------------------------
# 12-15: safe errors / state safety / concurrency
# ---------------------------------------------------------------------------


def test_approve_missing_job_is_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-approve", "999", "--note", "verified"])

    assert result.exit_code != 0
    assert result.exception is not None


def test_reject_missing_job_is_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-reject", "999", "--note", "reason"])

    assert result.exit_code != 0


def test_show_missing_job_is_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(cli_app, ["rights-show", "999"])

    assert result.exit_code != 0


def test_already_confirmed_job_cannot_be_silently_reapproved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepository()
    job_id = repo.seed(rights_confirmed=True)
    _patch(monkeypatch, repo)

    result = CliRunner().invoke(
        cli_app, ["rights-approve", str(job_id), "--note", "re-approve attempt"]
    )

    assert result.exit_code != 0
    assert "re-approve attempt" not in repo.jobs[job_id]["rights_note"]


def test_terminal_state_cannot_be_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed(status="uploaded", rights_confirmed=True)
    _patch(monkeypatch, repo)

    approve_result = CliRunner().invoke(
        cli_app, ["rights-approve", str(job_id), "--note", "attempt"]
    )
    reject_result = CliRunner().invoke(
        cli_app, ["rights-reject", str(job_id), "--note", "attempt"]
    )

    assert approve_result.exit_code != 0
    assert reject_result.exit_code != 0
    assert repo.jobs[job_id]["status"] == "uploaded"


def test_state_changed_underneath_operator_fails_safely_not_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulates a concurrent state change: approve once (succeeds), then
    # attempt to approve again (the atomic conditional update's WHERE
    # clause no longer matches - must return a safe conflict, not silently
    # re-apply or corrupt the row).
    repo = FakeRepository()
    job_id = repo.seed()
    _patch(monkeypatch, repo)

    first = CliRunner().invoke(cli_app, ["rights-approve", str(job_id), "--note", "first"])
    second = CliRunner().invoke(cli_app, ["rights-approve", str(job_id), "--note", "second"])

    assert first.exit_code == 0
    assert second.exit_code != 0
    assert "Operator verification: second" not in repo.jobs[job_id]["rights_note"]


# ---------------------------------------------------------------------------
# 16-17: isolation and secrecy
# ---------------------------------------------------------------------------


def test_approve_does_not_affect_other_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    target_id = repo.seed(source_title="target")
    other_id = repo.seed(source_title="other")
    _patch(monkeypatch, repo)

    CliRunner().invoke(cli_app, ["rights-approve", str(target_id), "--note", "verified"])

    assert repo.jobs[target_id]["rights_confirmed"] is True
    assert repo.jobs[other_id]["rights_confirmed"] is False
    assert repo.jobs[other_id]["status"] == "pending"


def test_no_secret_values_appear_in_cli_output(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    job_id = repo.seed(source_title="clip")
    _patch(monkeypatch, repo)

    list_result = CliRunner().invoke(cli_app, ["rights-list"])
    show_result = CliRunner().invoke(cli_app, ["rights-show", str(job_id)])
    approve_result = CliRunner().invoke(
        cli_app, ["rights-approve", str(job_id), "--note", "verified"]
    )

    for result in (list_result, show_result, approve_result):
        assert SECRET_SENTINEL not in result.output
