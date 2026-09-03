from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robin_content_engine.brain import (  # noqa: E402
    ApprovalContext,
    Brain,
    BrainPermissionError,
    FakeLLMClient,
    PermissionLevel,
    Tool,
    ToolRegistry,
    assert_allowed,
    parse_tool_call,
    make_registry,
    list_tools,
)


def _fake_registry(calls: list) -> ToolRegistry:
    reg = ToolRegistry(object())

    def record(name):
        def handler(settings, **args):
            calls.append((name, args))
            return {"ok": True, "output": f"{name}:{args}"}

        return handler

    reg.register(
        Tool(
            "status",
            "read-only status",
            PermissionLevel.READ_ONLY,
            {"type": "object", "properties": {}},
            record("status"),
        )
    )
    reg.register(
        Tool(
            "approve",
            "approve a job",
            PermissionLevel.REQUIRES_APPROVAL,
            {
                "type": "object",
                "properties": {"job_id": {"type": "integer"}},
                "required": ["job_id"],
            },
            record("approve"),
        )
    )
    reg.register(
        Tool(
            "make_public",
            "publish videos",
            PermissionLevel.HIGH_RISK,
            {"type": "object", "properties": {}},
            record("make_public"),
        )
    )
    return reg


# --------------------------------------------------------------------------- #
# parse_tool_call
# --------------------------------------------------------------------------- #
def test_parse_tool_call_clean() -> None:
    assert parse_tool_call('{"tool":"x","args":{"a":1}}') == ("x", {"a": 1})


def test_parse_tool_call_with_prose() -> None:
    assert parse_tool_call('sure, here: {"tool":"y","args":{}} done') == ("y", {})


def test_parse_tool_call_invalid() -> None:
    assert parse_tool_call("no json here") is None
    assert parse_tool_call('{"foo":1}') is None


# --------------------------------------------------------------------------- #
# assert_allowed
# --------------------------------------------------------------------------- #
def test_assert_allowed_read_only_always_ok() -> None:
    assert_allowed(PermissionLevel.READ_ONLY, None)
    assert_allowed(PermissionLevel.READ_ONLY, ApprovalContext())


def test_assert_allowed_requires_grant() -> None:
    ctx = ApprovalContext()
    with pytest.raises(BrainPermissionError):
        assert_allowed(PermissionLevel.HIGH_RISK, ctx, "make_public")
    ctx.grant("make_public")
    assert_allowed(PermissionLevel.HIGH_RISK, ctx, "make_public")


# --------------------------------------------------------------------------- #
# Registry gate
# --------------------------------------------------------------------------- #
def test_registry_read_only_executes_without_grant() -> None:
    calls: list = []
    reg = _fake_registry(calls)
    ctx = ApprovalContext()
    result = reg.execute("status", {}, ctx)
    assert result["ok"] is True
    assert calls == [("status", {})]


def test_registry_gate_blocks_high_risk_without_grant() -> None:
    calls: list = []
    reg = _fake_registry(calls)
    ctx = ApprovalContext()
    with pytest.raises(BrainPermissionError):
        reg.execute("make_public", {}, ctx)
    assert calls == []


def test_registry_gate_blocks_requires_approval_without_grant() -> None:
    calls: list = []
    reg = _fake_registry(calls)
    ctx = ApprovalContext()
    with pytest.raises(BrainPermissionError):
        reg.execute("approve", {"job_id": 3}, ctx)
    assert calls == []


# --------------------------------------------------------------------------- #
# Brain.ask
# --------------------------------------------------------------------------- #
def test_ask_read_only_executes() -> None:
    calls: list = []
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"status","args":{}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry(calls),
    )
    turn = brain.ask("status please")
    assert len(turn.executed) == 1
    assert turn.executed[0]["ok"] is True
    assert turn.pending == []
    assert calls == [("status", {})]


def test_ask_requires_approval_returns_pending_not_executed() -> None:
    calls: list = []
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"approve","args":{"job_id":7}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry(calls),
    )
    turn = brain.ask("approve job 7")
    assert turn.executed == []
    assert len(turn.pending) == 1
    assert turn.pending[0].tool == "approve"
    assert turn.pending[0].permission == PermissionLevel.REQUIRES_APPROVAL
    assert calls == []


def test_ask_high_risk_returns_pending_not_executed() -> None:
    calls: list = []
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"make_public","args":{}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry(calls),
    )
    turn = brain.ask("publish everything")
    assert turn.executed == []
    assert turn.pending[0].permission == PermissionLevel.HIGH_RISK
    assert calls == []


def test_ask_after_grant_executes() -> None:
    calls: list = []
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"approve","args":{"job_id":7}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry(calls),
    )
    before = brain.ask("approve 7")
    assert before.pending
    brain.grant("approve")
    after = brain.ask("approve 7")
    assert len(after.executed) == 1
    assert after.executed[0]["ok"] is True
    assert calls == [("approve", {"job_id": 7})]


def test_ask_run_pending_executes_high_risk() -> None:
    calls: list = []
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"make_public","args":{}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry(calls),
    )
    turn = brain.ask("publish")
    pending = turn.pending[0]
    result = brain.run_pending(pending)
    assert result["ok"] is True
    assert calls == [("make_public", {})]


def test_ask_unknown_tool_graceful_error() -> None:
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"bogus","args":{}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry([]),
    )
    turn = brain.ask("do bogus")
    assert turn.executed and turn.executed[0]["tool"] == "bogus"
    assert turn.executed[0]["ok"] is False
    assert turn.pending == []


def test_ask_invalid_json_graceful_chat_reply() -> None:
    brain = Brain(
        object(),
        FakeLLMClient("I cannot help with that."),
        ctx=ApprovalContext(),
        registry=_fake_registry([]),
    )
    turn = brain.ask("hi")
    assert turn.reply  # conversational reply, no crash
    assert turn.executed == []
    assert turn.pending == []


def test_ask_invalid_args_graceful_error() -> None:
    brain = Brain(
        object(),
        FakeLLMClient('{"tool":"approve","args":{}}'),
        ctx=ApprovalContext(),
        registry=_fake_registry([]),
    )
    turn = brain.ask("approve")
    assert turn.executed and turn.executed[0]["tool"] == "approve"
    assert turn.executed[0]["ok"] is False
    assert turn.pending == []


# --------------------------------------------------------------------------- #
# make_registry / list_tools shape (no DB / Ollama touched)
# --------------------------------------------------------------------------- #
def test_make_registry_shape() -> None:
    reg = make_registry(object())
    names = {t.name for t in reg.list()}
    expected = {
        "status",
        "system",
        "plan",
        "long_videos",
        "scan",
        "sync",
        "import",
        "metafix",
        "metafix_apply",
        "approve",
        "run_once_noupload",
        "run_once",
        "make_public",
    }
    assert names == expected
    by_name = {t.name: t for t in reg.list()}
    assert by_name["status"].permission == PermissionLevel.READ_ONLY
    assert by_name["system"].permission == PermissionLevel.READ_ONLY
    assert by_name["plan"].permission == PermissionLevel.READ_ONLY
    assert by_name["long_videos"].permission == PermissionLevel.READ_ONLY
    assert by_name["scan"].permission == PermissionLevel.SAFE_WRITE
    assert by_name["sync"].permission == PermissionLevel.SAFE_WRITE
    assert by_name["import"].permission == PermissionLevel.SAFE_WRITE
    assert by_name["metafix"].permission == PermissionLevel.SAFE_WRITE
    assert by_name["metafix_apply"].permission == PermissionLevel.REQUIRES_APPROVAL
    assert by_name["approve"].permission == PermissionLevel.REQUIRES_APPROVAL
    assert by_name["run_once_noupload"].permission == PermissionLevel.REQUIRES_APPROVAL
    assert by_name["run_once"].permission == PermissionLevel.HIGH_RISK
    assert by_name["make_public"].permission == PermissionLevel.HIGH_RISK


def test_list_tools_returns_catalog() -> None:
    catalog = list_tools(object())
    assert len(catalog) == 13
    for entry in catalog:
        assert set(entry.keys()) == {"name", "description", "permission"}
