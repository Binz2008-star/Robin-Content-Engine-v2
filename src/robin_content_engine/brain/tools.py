from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .permissions import ApprovalContext, PermissionLevel, assert_allowed


@dataclass
class Tool:
    name: str
    description: str
    permission: PermissionLevel
    args_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class ToolRegistry:
    """Registry of operator tools with a single, centralized permission gate.

    The permission check lives only in `execute()` so a handler can never be
    reached outside the guard. Handlers are narrow, explicit functions and are
    never handed arbitrary shell/SQL/code.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> Tool:
        return self._tools[tool_name]

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ApprovalContext | None,
    ) -> dict[str, Any]:
        tool = self.get(tool_name)
        assert_allowed(tool.permission, ctx, tool_name)
        return tool.handler(self._settings, **args)
