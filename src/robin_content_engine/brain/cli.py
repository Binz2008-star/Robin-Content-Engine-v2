from __future__ import annotations

import os
from typing import Any

import typer

from ..config import Settings
from .actions import ApprovalContext, Brain, make_registry
from .permissions import PermissionLevel


def _brain_enabled() -> bool:
    return os.environ.get("ROBIN_BRAIN_ENABLED", "False").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def register_brain(app: "typer.Typer") -> None:
    """Wire the `brain` command group onto an existing Typer app.

    This is import-safe and never raises on its own; the heavy agent objects are
    only constructed inside the command bodies. The operator-facing `ask` command
    honors the ROBIN_BRAIN_ENABLED opt-in flag.
    """
    brain_app = typer.Typer(no_args_is_help=True, help="Robin Brain operator-assistant agent")

    @brain_app.command("ask")
    def ask_cmd(prompt: str) -> None:
        if not _brain_enabled():
            typer.echo(
                "Robin Brain is disabled. Set ROBIN_BRAIN_ENABLED=true to use it."
            )
            raise typer.Exit(code=2)
        settings = Settings()
        try:
            brain = Brain.from_settings(settings)
        except Exception as exc:
            typer.echo(f"Failed to start Robin Brain: {exc}")
            raise typer.Exit(code=1) from exc

        turn = brain.ask(prompt)
        for entry in turn.executed:
            tool = entry.get("tool", "?")
            ok = entry.get("ok")
            output = entry.get("output", "")
            typer.echo(f"[executed] {tool} ok={ok}: {output}")
        for pending in turn.pending:
            typer.echo(
                f"[pending] {pending.permission.value} action: "
                f"{pending.tool} — {pending.description}"
            )
            typer.echo(f"  args={pending.args}")
            if typer.confirm("Approve and run this action now?", default=False):
                try:
                    result = brain.run_pending(pending)
                    typer.echo(
                        f"  -> ok={result.get('ok')}: {result.get('output')}"
                    )
                except Exception as exc:
                    typer.echo(f"  -> error: {exc}")
            else:
                typer.echo("  -> skipped (not run).")

    @brain_app.command("tools")
    def tools_cmd() -> None:
        settings = Settings()
        registry = make_registry(settings)
        for tool in registry.list():
            typer.echo(
                f"{tool.name:20s} {tool.permission.value:18s} {tool.description}"
            )

    @brain_app.command("grant")
    def grant_cmd(tool: str) -> None:
        settings = Settings()
        registry = make_registry(settings)
        try:
            registry.get(tool)
        except KeyError:
            typer.echo(f"Unknown tool: {tool}")
            raise typer.Exit(code=2) from None
        ctx = ApprovalContext()
        ctx.grant(tool)
        typer.echo(
            f"Granted '{tool}' for this session. Note: grants are per-process; "
            "use the interactive `ask` flow for approvals that persist across the loop."
        )

    app.add_typer(brain_app, name="brain")
