from __future__ import annotations

from enum import Enum
from typing import Iterable


class PermissionLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE_WRITE = "SAFE_WRITE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    HIGH_RISK = "HIGH_RISK"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK: dict["PermissionLevel", int] = {
    PermissionLevel.READ_ONLY: 0,
    PermissionLevel.SAFE_WRITE: 1,
    PermissionLevel.REQUIRES_APPROVAL: 2,
    PermissionLevel.HIGH_RISK: 3,
}


class BrainPermissionError(PermissionError):
    """Raised when a tool requires an operator grant that has not been given."""


class ApprovalContext:
    """Holds the operator's session-scoped grants.

    Grants are keyed by tool name. A READ_ONLY tool never needs a grant;
    every other tool must be explicitly granted by the operator before it can
    be executed. The model can never grant to itself.
    """

    def __init__(self, granted: Iterable[str] | None = None) -> None:
        self._granted: set[str] = set(granted or set())

    def grant(self, tool_name: str) -> None:
        self._granted.add(tool_name)

    def revoke(self, tool_name: str) -> None:
        self._granted.discard(tool_name)

    def is_granted(self, tool_name: str) -> bool:
        return tool_name in self._granted

    def granted(self) -> frozenset[str]:
        return frozenset(self._granted)


def assert_allowed(
    level: PermissionLevel,
    ctx: "ApprovalContext | None",
    tool_name: str | None = None,
) -> None:
    """Enforce the default-deny permission model.

    READ_ONLY is always allowed. Anything else requires an explicit grant for
    the specific tool name held in `ctx`. This is fail-closed: if the level is
    not READ_ONLY and no matching grant is present, it raises.
    """
    if level == PermissionLevel.READ_ONLY:
        return
    if ctx is None or tool_name is None or not ctx.is_granted(tool_name):
        target = tool_name or "<unknown>"
        raise BrainPermissionError(
            f"tool '{target}' requires operator approval (level={level.value}) "
            f"but was not granted for this session"
        )
