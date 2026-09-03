"""Robin Brain: a local, operator-assistant AI agent for the Robin Content
Engine with a strict default-deny permission model.

This package is opt-in and import-safe: importing it never touches the heavy
production dependencies (those are imported lazily inside `make_registry`), and
all agent construction is lazy. `ROBIN_BRAIN_ENABLED` defaults to False.
"""

from .actions import (
    Brain,
    BrainTurn,
    PendingAction,
    list_tools,
    make_registry,
)
from .llm import FakeLLMClient, LLMClient, OllamaLLMClient, parse_tool_call
from .permissions import (
    ApprovalContext,
    BrainPermissionError,
    PermissionLevel,
    assert_allowed,
)
from .tools import Tool, ToolRegistry

__all__ = [
    "Brain",
    "BrainTurn",
    "PendingAction",
    "PermissionLevel",
    "Tool",
    "ToolRegistry",
    "ApprovalContext",
    "BrainPermissionError",
    "list_tools",
    "make_registry",
    "LLMClient",
    "OllamaLLMClient",
    "FakeLLMClient",
    "parse_tool_call",
    "assert_allowed",
]
