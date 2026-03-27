"""
mc chat / mc design — conversational REPL handlers for the user CLI.

Chat streams agent responses in real-time using the handle() AsyncIterator.
Design wraps WorkflowArchitectService for multi-turn workflow creation.
"""

import json

import click

from modules.clients.common.display import get_console
from modules.clients.common.event_rendering import format_event_line


async def chat_repl(
    agent_name: str | None = None,
    initial_message: str | None = None,
    mission_id: str = "",
    verbose: bool = False,
) -> None:
    """Interactive chat with the coordinator or a specific agent.

    Uses the simple-agent path in handle() with conversation history.
    The agent is pinned on the session so _resolve_agent picks it up
    on every turn — no keyword routing ambiguity.
    """
    from modules.backend.agents.mission_control.helpers import get_chat_agent
    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.core.database import get_async_session
    from modules.backend.schemas.session import SessionCreate
    from modules.backend.services.mission import MissionService
    from modules.backend.services.session import SessionService

    console = get_console()

    # Suppress console log noise during chat (warnings from dispatch loop etc.)
    # Verbose mode keeps full logging; normal mode silences everything below CRITICAL.
    if not verbose:
        import logging
        logging.getLogger().setLevel(logging.CRITICAL)

    # Resolve which agent to chat with
    target_agent = agent_name or get_chat_agent()

    # Create a session pinned to the target agent
    async with get_async_session() as db:
        session_svc = SessionService(db)
        session = await session_svc.create_session(
            SessionCreate(goal="mc chat", agent_id=target_agent),
        )
        session_id = str(session.id)
        await db.commit()

    # Load mission name for display
    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)

    agent_label = target_agent.split(".")[-2] if "." in target_agent else target_agent
    if verbose:
        click.echo(f"Mission Control — {mission.name} [{target_agent}]")
    else:
        console.print(
            f"[bold cyan]Mission Control[/bold cyan] — {mission.name} "
            f"[dim]({agent_label})[/dim]"
        )
    click.echo("Type /exit to quit. Ctrl+C to cancel current response.\n")

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

        if not verbose:
            console.print()
        try:
            async with get_async_session() as db:
                session_svc = SessionService(db)
                async for event in handle(
                    session_id=session_id,
                    message=user_input,
                    session_service=session_svc,
                    channel="mc",
                    mission_id=mission_id,
                    db_session=db,
                ):
                    if verbose:
                        _render_chat_event_verbose(event)
                    else:
                        _render_chat_event(console, event)
                await db.commit()
        except KeyboardInterrupt:
            click.echo("\nCancelled.")

        if not verbose:
            console.print()


async def design_repl(
    description: str | None,
    mission_id: str,
    verbose: bool = False,
) -> None:
    """Interactive workflow design with the Architect."""
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    console = get_console()
    message_history: list = []

    if verbose:
        click.echo("Workflow Architect")
    else:
        console.print("[bold cyan]Workflow Architect[/bold cyan]")
    click.echo("Describe what you want to automate. Type /exit to quit.\n")

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

        if verbose:
            print(json.dumps({"type": "architect_response", "response": response}, default=str), flush=True)
            workflow_yaml = result.get("workflow_yaml")
            if workflow_yaml:
                print(json.dumps({"type": "workflow_generated", "yaml": workflow_yaml}, default=str), flush=True)
        else:
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
        if event.metadata and event.metadata.get("error"):
            console.print(f"  [bold red]Error:[/bold red] {event.full_content}")
        elif event.cost_usd > 0:
            console.print(
                f"[dim]  ${event.cost_usd:.4f} | "
                f"{event.input_tokens + event.output_tokens:,} tokens[/dim]"
            )

    else:
        console.print(f"  {format_event_line(event)}")


def _render_chat_event_verbose(event):
    """Print event as JSONL — no Rich formatting."""
    from modules.backend.events.types import AgentResponseChunkEvent

    # Skip noisy streaming chunks in verbose mode; aggregate in complete event
    if isinstance(event, AgentResponseChunkEvent):
        return

    data = event.model_dump(mode="json")
    print(json.dumps(data, default=str), flush=True)
