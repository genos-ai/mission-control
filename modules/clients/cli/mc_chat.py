"""
mc chat / mc design — conversational REPL handlers for the user CLI.

Chat streams agent responses in real-time using the handle() AsyncIterator.
Design wraps WorkflowArchitectService for multi-turn workflow creation.
"""

import click

from modules.clients.common.display import get_console
from modules.clients.common.event_rendering import format_event_line


async def chat_repl(
    agent_name: str | None = None,
    initial_message: str | None = None,
    mission_id: str = "",
) -> None:
    """Interactive chat with the coordinator or a specific agent."""
    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.core.database import get_async_session
    from modules.backend.events.types import (
        AgentResponseChunkEvent,
        AgentResponseCompleteEvent,
    )
    from modules.backend.schemas.session import SessionCreate
    from modules.backend.services.mission import MissionService
    from modules.backend.services.session import SessionService

    console = get_console()

    # Create a session for multi-turn conversation
    async with get_async_session() as db:
        session_svc = SessionService(db)
        session = await session_svc.create_session(
            SessionCreate(goal="mc chat"),
        )
        session_id = str(session.id)
        await db.commit()

    # Load mission brief
    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)
    mission_brief = mission.brief

    console.print(f"[bold cyan]Mission Control[/bold cyan] — {mission.name}")
    console.print(f"[dim]Type /exit to quit. Ctrl+C to cancel current response.[/dim]\n")

    while True:
        if initial_message:
            user_input = initial_message
            initial_message = None
        else:
            try:
                user_input = click.prompt("you", prompt_suffix=" > ")
            except (click.Abort, EOFError):
                break

        if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
            break

        console.print()
        try:
            async with get_async_session() as db:
                session_svc = SessionService(db)
                async for event in handle(
                    session_id=session_id,
                    message=user_input,
                    session_service=session_svc,
                    channel="mc",
                    mission_brief=mission_brief if not agent_name else None,
                ):
                    _render_chat_event(console, event)
                await db.commit()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")

        console.print()


async def design_repl(description: str | None, mission_id: str) -> None:
    """Interactive workflow design with the Architect."""
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    console = get_console()
    message_history: list = []

    console.print("[bold cyan]Workflow Architect[/bold cyan]")
    console.print("[dim]Describe what you want to automate. Type /exit to quit.[/dim]\n")

    user_input = description
    if not user_input:
        try:
            user_input = click.prompt("you", prompt_suffix=" > ")
        except (click.Abort, EOFError):
            return

    while True:
        async with WorkflowArchitectService.factory() as svc:
            result = await svc.chat(
                mission_id=mission_id,
                message=user_input,
                message_history=message_history,
            )

        response = result.get("response", "")
        new_history = result.get("all_messages", [])
        if new_history:
            message_history = new_history

        console.print(f"\n[bold cyan]architect:[/bold cyan] {response}\n")

        workflow_yaml = result.get("workflow_yaml")
        if workflow_yaml:
            console.print("[green]Workflow generated. Save with /save <name>[/green]")

        try:
            user_input = click.prompt("you", prompt_suffix=" > ")
        except (click.Abort, EOFError):
            break

        if user_input.strip().lower() in ("/exit", "/quit"):
            break


def _render_chat_event(console, event):
    """Render a SessionEvent inline in the chat stream.

    Reuses format_event_line() from event_rendering.py for all
    non-streaming events. Only AgentResponseChunkEvent needs special
    handling (raw text output without line formatting).
    """
    from modules.backend.events.types import (
        AgentResponseChunkEvent,
        AgentResponseCompleteEvent,
    )

    if isinstance(event, AgentResponseChunkEvent):
        console.file.write(event.content)
        console.file.flush()

    elif isinstance(event, AgentResponseCompleteEvent):
        console.print()
        if event.cost_usd > 0:
            console.print(
                f"[dim]  ${event.cost_usd:.4f} | "
                f"{event.input_tokens + event.output_tokens:,} tokens[/dim]"
            )

    else:
        console.print(f"  {format_event_line(event)}")
