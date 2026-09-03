from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from .llm import LLMClient, OllamaLLMClient, parse_brain_response, parse_tool_call
from .permissions import ApprovalContext, PermissionLevel
from .tools import Tool, ToolRegistry


def _brain_enabled() -> bool:
    return os.environ.get("ROBIN_BRAIN_ENABLED", "False").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@dataclass
class PendingAction:
    tool: str
    args: dict[str, Any]
    permission: PermissionLevel
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "permission": self.permission.value,
            "description": self.description,
        }


@dataclass
class BrainTurn:
    executed: list[dict[str, Any]] = field(default_factory=list)
    pending: list[PendingAction] = field(default_factory=list)
    reply: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "executed": self.executed,
            "pending": [p.to_dict() for p in self.pending],
        }


class Brain:
    """Local operator-assistant agent with a strict default-deny permission model.

    The agent never calls native LLM tool-calling. It receives the tool catalog
    in the system prompt and returns a single strict JSON tool call, which this
    class validates and routes through the registry's permission gate.
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: LLMClient,
        ctx: ApprovalContext | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.ctx = ctx or ApprovalContext()
        self.registry = registry or make_registry(settings)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        llm_client: LLMClient | None = None,
    ) -> "Brain":
        registry = make_registry(settings)
        if llm_client is None:
            if not _brain_enabled():
                raise RuntimeError(
                    "Robin Brain is disabled (ROBIN_BRAIN_ENABLED). "
                    "Enable it or pass an explicit llm_client."
                )
            llm_client = OllamaLLMClient()
        return cls(settings, llm_client, registry=registry)

    def grant(self, tool_name: str) -> None:
        self.ctx.grant(tool_name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "permission": t.permission.value,
            }
            for t in self.registry.list()
        ]

    def ask(
        self,
        prompt: str,
        history: list[dict[str, Any]] | None = None,
    ) -> BrainTurn:
        """Run one conversational turn.

        ``history`` is a list of prior messages (each ``{"role": "user"|"brain",
        "text": ...}``) used to give the model multi-turn context. The model
        returns a JSON object with a natural-language ``reply`` and an optional
        ``tool`` call; pure chat (no tool) returns an empty ``executed`` list.
        """
        system = self._build_system_prompt()
        user_prompt = self._build_user_prompt(prompt, history)
        try:
            raw = self.llm_client.complete(system, user_prompt)
        except Exception as exc:
            return BrainTurn(
                reply="I could not reach the model.",
                executed=[
                    {
                        "tool": "<llm_error>",
                        "ok": False,
                        "output": f"{type(exc).__name__}: {exc}",
                    }
                ],
            )

        parsed = parse_brain_response(raw)
        reply = parsed["reply"]
        tool_name = parsed["tool"]
        if tool_name is None:
            return BrainTurn(reply=reply or raw.strip())

        args = parsed["args"]

        try:
            tool = self.registry.get(tool_name)
        except KeyError:
            return BrainTurn(
                reply=reply,
                executed=[
                    {
                        "tool": tool_name,
                        "ok": False,
                        "output": f"Unknown tool: {tool_name}",
                    }
                ],
            )

        try:
            args = _coerce_args(tool.args_schema, args)
        except Exception as exc:
            return BrainTurn(
                reply=reply,
                executed=[
                    {
                        "tool": tool_name,
                        "ok": False,
                        "output": f"Invalid args for {tool_name}: {exc}",
                    }
                ],
            )

        if tool.permission == PermissionLevel.READ_ONLY or self.ctx.is_granted(tool_name):
            try:
                result = self.registry.execute(tool_name, args, self.ctx)
            except Exception as exc:
                result = {"ok": False, "output": f"{type(exc).__name__}: {exc}"}
            if not isinstance(result, dict) or "ok" not in result:
                if isinstance(result, dict):
                    result = {"ok": True, **result}
                else:
                    result = {"ok": True, "output": result}
            return BrainTurn(
                reply=reply,
                executed=[{"tool": tool_name, **result}],
                pending=[],
            )

        return BrainTurn(
            reply=reply,
            executed=[],
            pending=[
                PendingAction(
                    tool=tool_name,
                    args=args,
                    permission=tool.permission,
                    description=tool.description,
                )
            ],
        )

    def _build_user_prompt(
        self,
        prompt: str,
        history: list[dict[str, Any]] | None,
    ) -> str:
        if not history:
            return prompt
        lines: list[str] = []
        for message in history:
            role = message.get("role")
            text = message.get("text") or message.get("content") or ""
            if role == "user":
                lines.append(f"Operator: {text}")
            else:
                lines.append(f"Robin Brain: {text}")
        lines.append("")
        lines.append(f"Operator: {prompt}")
        return "\n".join(lines)

    def run_pending(self, pending: PendingAction) -> dict[str, Any]:
        self.grant(pending.tool)
        return self.registry.execute(pending.tool, pending.args, self.ctx)

    def _build_system_prompt(self) -> str:
        lines = [
            "You are Robin Brain, a local operator-assistant for the Robin "
            "Content Engine, a YouTube Shorts production pipeline. You help the "
            "operator inspect and drive the pipeline. You do NOT have autonomous "
            "power: publishing and material changes require explicit operator "
            "approval. You communicate like a colleague chatting with the "
            "operator: friendly, concise, and clear.",
            "",
            "Respond with EXACTLY ONE JSON object of the form:",
            '{"reply": "<short natural-language reply to the operator>", '
            '"tool": "<tool_name or null>", "args": { ... }}',
            'Set "tool" to null when you are only chatting and no action is '
            "needed. The reply must be conversational and written for a human.",
            "",
            "Tool catalog (name | permission | description | args schema):",
        ]
        for tool in self.registry.list():
            lines.append(
                f"  - {tool.name} ({tool.permission.value}): {tool.description}"
            )
            lines.append(f"    args: {json.dumps(tool.args_schema)}")
        lines.append("")
        lines.append("Rules:")
        lines.append(
            "- READ_ONLY tools are safe; use them freely to answer questions, and "
            "your reply should summarize what they returned."
        )
        lines.append(
            "- SAFE_WRITE, REQUIRES_APPROVAL, and HIGH_RISK tools change state or "
            "publish. Only call them when the operator explicitly requested that "
            "action, and your reply must state exactly what you will do and that "
            "it needs the operator's approval."
        )
        lines.append(
            "- Never invent tool names. If the request cannot be fulfilled by a "
            'tool, set "tool": null and just chat about it.'
        )
        lines.append('- Return only one JSON object per response, no extra text '
                     "outside it unless it is the prose reply inside \"reply\".")
        lines.append(
            "- The Operator may refer to earlier messages; use the conversation "
            "history for context before choosing a tool or replying."
        )
        return "\n".join(lines)


def _coerce_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = schema.get("properties", {})
    out: dict[str, Any] = dict(args)
    for name, spec in properties.items():
        if name not in out:
            if "default" in spec:
                out[name] = spec["default"]
            continue
        value = out[name]
        type_ = spec.get("type")
        if type_ == "integer" and not isinstance(value, int):
            out[name] = int(value)
        elif type_ == "number" and not isinstance(value, float):
            out[name] = float(value)
        elif type_ == "boolean" and not isinstance(value, bool):
            out[name] = (
                str(value).strip().lower() in ("1", "true", "yes", "y", "on")
                if isinstance(value, str)
                else bool(value)
            )
    missing = [r for r in schema.get("required", []) if r not in out]
    if missing:
        raise ValueError(f"missing required args: {missing}")
    return out


def make_registry(settings: Settings) -> ToolRegistry:
    """Build the full operator-tool registry from `ops_actions`.

    `ops_actions` is imported lazily so importing the brain package never pulls
    in the heavy production dependencies unless a registry is actually built.
    """
    from .. import ops_actions

    registry = ToolRegistry(settings)

    no_args: dict[str, Any] = {"type": "object", "properties": {}}

    def add(
        name: str,
        description: str,
        permission: PermissionLevel,
        args_schema: dict[str, Any],
        handler: Any,
    ) -> None:
        registry.register(
            Tool(
                name=name,
                description=description,
                permission=permission,
                args_schema=args_schema,
                handler=handler,
            )
        )

    add(
        "status",
        "Show production pipeline status: counts of jobs by state and recent jobs.",
        PermissionLevel.READ_ONLY,
        dict(no_args),
        lambda s, **a: ops_actions.status(s),
    )
    add(
        "system",
        "Show system info: YouTube auth state, database connectivity, key settings.",
        PermissionLevel.READ_ONLY,
        dict(no_args),
        lambda s, **a: ops_actions.system_info(s),
    )
    add(
        "plan",
        "Show the resumable metadata-fix plan status (pending videos, done count).",
        PermissionLevel.READ_ONLY,
        dict(no_args),
        lambda s, **a: ops_actions.metadata_plan_status(s),
    )
    add(
        "long_videos",
        "List long videos available for import as Shorts (local media analysis, read-only).",
        PermissionLevel.READ_ONLY,
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 30},
                "min_seconds": {"type": "integer", "default": 60},
            },
        },
        lambda s, **a: ops_actions.long_videos(
            s, limit=a.get("limit", 30), min_seconds=a.get("min_seconds", 60)
        ),
    )
    add(
        "scan",
        "Scan capture directories and register new captures (reversible local write).",
        PermissionLevel.SAFE_WRITE,
        dict(no_args),
        lambda s, **a: ops_actions.scan(s),
    )
    add(
        "sync",
        "Refresh the channel snapshot into the local database (reversible local write).",
        PermissionLevel.SAFE_WRITE,
        dict(no_args),
        lambda s, **a: ops_actions.sync(s),
    )
    add(
        "import",
        "Import a YouTube video as a Short job (queued, not uploaded).",
        PermissionLevel.SAFE_WRITE,
        {
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "upload": {"type": "boolean", "default": False},
            },
            "required": ["video_id"],
        },
        lambda s, **a: ops_actions.import_video(
            s, video_id=a["video_id"], upload=a.get("upload", False)
        ),
    )
    add(
        "metafix",
        "Build (but do not apply) the YouTube metadata-fix plan (read of plan, no external write).",
        PermissionLevel.SAFE_WRITE,
        dict(no_args),
        lambda s, **a: ops_actions.metadata_fix(s, apply=False),
    )
    add(
        "metafix_apply",
        "Apply the built YouTube metadata-fix plan (writes metadata to YouTube).",
        PermissionLevel.REQUIRES_APPROVAL,
        dict(no_args),
        lambda s, **a: ops_actions.metadata_fix(s, apply=True),
    )
    add(
        "approve",
        "Approve rights for a job (operator decision that materially changes the queue).",
        PermissionLevel.REQUIRES_APPROVAL,
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["job_id"],
        },
        lambda s, **a: ops_actions.approve(s, job_id=a["job_id"], note=a.get("note")),
    )
    add(
        "run_once_noupload",
        "Run the production step once and dry-run publish (no upload, no external write).",
        PermissionLevel.REQUIRES_APPROVAL,
        dict(no_args),
        lambda s, **a: ops_actions.run_once(s, upload=False),
    )
    add(
        "run_once",
        "Run the production step once and upload the resulting Short privately to YouTube.",
        PermissionLevel.HIGH_RISK,
        dict(no_args),
        lambda s, **a: ops_actions.run_once(s, upload=True),
    )
    add(
        "make_public",
        "Make all currently-private uploaded videos public on YouTube (external publish).",
        PermissionLevel.HIGH_RISK,
        dict(no_args),
        lambda s, **a: ops_actions.make_public(s),
    )
    return registry


def list_tools(settings: Settings) -> list[dict[str, Any]]:
    """Convenience: return the tool catalog (name/description/permission)."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "permission": t.permission.value,
        }
        for t in make_registry(settings).list()
    ]
