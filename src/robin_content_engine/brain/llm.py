from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Abstraction over a completion model. The agent loop does NOT use native
    tool-calling; it sends the tool catalog in the system prompt and parses a
    strict JSON `{"tool": ..., "args": ...}` response instead (suitable for a
    local 7B Ollama model)."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        model: str | None = None,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model or os.environ.get("ROBIN_BRAIN_MODEL", "qwen2.5:7b")
        self.base_url = base_url.rstrip("/")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "format": "json",
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body.get("response", ""))


class FakeLLMClient(LLMClient):
    """Deterministic client for tests: always returns the provided string."""

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


def parse_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract `{"tool": <name>, "args": {...}}` from model output.

    Tolerates prose around the JSON by locating the outermost balanced braces.
    Returns None when no valid tool call can be found.
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    tool = obj.get("tool")
    args = obj.get("args")
    if not isinstance(tool, str) or not isinstance(args, dict):
        return None
    return tool, args


def parse_brain_response(text: str) -> dict[str, Any]:
    """Parse a conversational model response into a structured brain action.

    Returns ``{"reply": <str>, "tool": <str|None>, "args": <dict>}``.

    The model should return JSON of the form
    ``{"reply": "...", "tool": "<name|null>", "args": {...}}``. When only prose
    is present (no JSON) the whole text becomes the ``reply`` and ``tool`` is
    ``None`` (a pure chat turn). When JSON is present but has no ``reply`` key,
    any prose outside the JSON is used as the reply, falling back to a short
    acknowledgement so the agent always talks back.
    """
    if not text:
        return {"reply": "", "tool": None, "args": {}}
    start = text.find("{")
    end = text.rfind("}")
    obj = None
    if start != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            obj = json.loads(snippet)
        except json.JSONDecodeError:
            obj = None
    if isinstance(obj, dict):
        tool = obj.get("tool")
        args = obj.get("args", {})
        if not isinstance(args, dict):
            args = {}
        reply = obj.get("reply")
        if not isinstance(reply, str):
            reply = ""
        if not reply:
            prose = (text[:start] + text[end + 1 :]).strip()
            if prose:
                reply = prose
            elif isinstance(tool, str):
                reply = f"On it - running {tool}."
        if tool is not None and not isinstance(tool, str):
            tool = None
        return {"reply": reply, "tool": tool, "args": args}
    return {"reply": text.strip(), "tool": None, "args": {}}
