"""
CLI handler for Workflow Architect commands.

Thin renderer over WorkflowArchitectService. Supports single-message
chat mode for non-interactive use.
"""

import asyncio
import sys

from modules.clients.cli.report import get_console


def run_architect(
    cli_logger,
    action: str,
    *,
    mission_id: str | None = None,
    message: str | None = None,
    output_format: str = "human",
) -> None:
    """Dispatch architect CLI actions."""
    actions = {
        "chat": _action_chat,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(
        cli_logger,
        mission_id=mission_id,
        message=message,
        output_format=output_format,
    ))


async def _action_chat(cli_logger, *, mission_id, message, output_format, **_):
    """Send a single message to the Workflow Architect."""
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    console = get_console()
    if not mission_id:
        console.print("[red]--mission is required[/red]")
        sys.exit(1)
    if not message:
        console.print("[red]--message is required[/red]")
        sys.exit(1)

    async with WorkflowArchitectService.factory() as svc:
        result = await svc.chat(
            mission_id=mission_id,
            message=message,
        )

    response = result.get("response", "")
    console.print(f"\n[bold]Workflow Architect:[/bold]\n")
    console.print(response)

    usage = result.get("usage")
    if usage:
        console.print(f"\n[dim]Usage: {usage}[/dim]")
