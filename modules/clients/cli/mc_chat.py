"""
mc chat / mc design — API-based conversational REPL handlers.

Chat streams agent responses via SSE. Design wraps the workflow
architect endpoint. Zero backend service imports.
"""

import json
from urllib.parse import quote

import click

from modules.clients.cli.api_client import CliApiClient
from modules.clients.common.display import get_console


async def chat_repl(
    api: CliApiClient,
    agent_name: str | None = None,
    initial_message: str | None = None,
    mission_id: str = "",
    verbose: bool = False,
    new_thread: bool = False,
) -> None:
    """Interactive chat with the coordinator or a specific agent.

    Reuses the most recent active session by default (shared with the
    web frontend). Pass new_thread=True (--new flag) to start fresh.
    """
    console = get_console()

    # Default to mission director when no agent specified
    if not agent_name:
        agent_name = "mission.director.agent"

    # Resolve or create session (shared across all agents in the mission)
    session_id = None

    if not new_thread:
        params: dict = {"mission_id": mission_id, "status": "ACTIVE", "limit": 1}
        sessions = await api.get("/sessions", params=params)
        session_list = sessions if isinstance(sessions, list) else sessions.get("items", [])
        if session_list:
            session_id = session_list[0].get("id")

    if not session_id:
        session = await api.post("/sessions", body={
            "goal": "Mission Chat",
            "agent_id": "mission.director.agent",
            "mission_id": mission_id,
        })
        session_id = session.get("id")

    # Display header
    mission = await api.get(f"/missions/{mission_id}")
    agent_label = agent_name.split(".")[-2] if "." in agent_name else agent_name

    if verbose:
        click.echo(f"Mission Control \u2014 {mission.get('name', '')} [{agent_name}]")
    else:
        console.print(
            f"[bold cyan]Mission Control[/bold cyan] \u2014 {mission.get('name', '')} "
            f"[dim]({agent_label})[/dim]"
        )
    click.echo("Type /exit to quit. Ctrl+C to cancel current response.\n")

    # REPL loop
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
            body: dict = {
                "message": user_input,
                "mission_id": mission_id,
                "session_id": session_id,
                "agent": agent_name,
            }

            saw_chunks = False
            async for sse in api.stream_sse("POST", "/agents/chat/stream", body=body):
                event_type = sse.get("event", "")
                data = sse.get("data", {})
                evt = data.get("event_type", event_type)

                if evt == "agent.response.chunk":
                    saw_chunks = True

                if verbose:
                    _render_sse_verbose(event_type, data)
                else:
                    _render_sse_event(console, event_type, data, suppress_body=saw_chunks)

        except KeyboardInterrupt:
            click.echo("\nCancelled.")

        if not verbose:
            console.print()


def _format_tool_trace(trace: list[dict]) -> str:
    """Render the architect's tool trace as `name ✓` / `name ✗` chips.

    Pairs each call with its matching result by tool_call_id so the user
    sees exactly which tools actually ran and whether each one succeeded.
    """
    if not trace:
        return ""
    results_by_id: dict[str, str] = {}
    for entry in trace:
        if entry.get("phase") == "result":
            results_by_id[entry.get("tool_call_id", "")] = entry.get("status", "")
    chips: list[str] = []
    for entry in trace:
        if entry.get("phase") != "call":
            continue
        name = entry.get("tool", "?")
        status = results_by_id.get(entry.get("tool_call_id", ""))
        glyph = "✓" if status == "success" else ("✗" if status == "error" else "…")
        chips.append(f"{name} {glyph}")
    return ", ".join(chips)


async def design_repl(
    api: CliApiClient,
    description: str | None,
    mission_id: str,
    verbose: bool = False,
) -> None:
    """Interactive workflow design with the Architect."""
    console = get_console()

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
        # Endpoint expects ?message=... as a query parameter (architect_chat
        # in missions_workflows.py). Multi-turn continuity is via session_id
        # on the endpoint side, not by client-sent history.
        result = await api.post(
            f"/missions/{mission_id}/architect/chat?message={quote(user_input)}",
        )

        response = result.get("response", "")
        tool_trace = result.get("tool_trace") or []
        tool_summary = _format_tool_trace(tool_trace)

        if verbose:
            if tool_trace:
                print(json.dumps({"type": "tool_trace", "trace": tool_trace}, default=str), flush=True)
            print(json.dumps({"type": "architect_response", "response": response}, default=str), flush=True)
            workflow_yaml = result.get("workflow_yaml")
            if workflow_yaml:
                print(json.dumps({"type": "workflow_generated", "yaml": workflow_yaml}, default=str), flush=True)
        else:
            if tool_summary:
                console.print(f"\n[dim]tools: {tool_summary}[/dim]")
            console.print(f"\n[bold cyan]architect:[/bold cyan] {response}\n")
            if result.get("workflow_yaml"):
                console.print("[green]Workflow generated. Save with /save <name>[/green]")

        try:
            user_input = click.prompt("you", prompt_suffix=" > ")
        except (click.Abort, EOFError):
            break

        if user_input.strip().lower() in ("/exit", "/quit"):
            break


# =============================================================================
# SSE event rendering
# =============================================================================


def _render_sse_event(
    console, event_type: str, data: dict, suppress_body: bool = False,
) -> None:
    """Render an SSE event inline in the chat stream.

    The API sends dot-notation event types:
      agent.response.chunk     — streaming text fragment
      agent.response.complete  — full response with cost
      agent.thinking.started   — agent is thinking
      agent.tool.called        — tool invocation
      agent.tool.returned      — tool result
      session.cost.updated     — cumulative cost
      user.message.sent        — echo of user input
      done                     — stream end

    When chunks have already streamed the text, suppress_body=True
    prevents the complete event from printing full_content again.
    """
    evt = data.get("event_type", event_type)

    if evt == "agent.response.chunk":
        content = data.get("content", "")
        console.file.write(content)
        console.file.flush()

    elif evt == "agent.response.complete":
        full = data.get("full_content", "")
        # Only print body if chunks didn't already stream it
        if not suppress_body and full:
            console.print(full)
        cost = data.get("cost_usd", 0)
        if data.get("metadata", {}).get("error"):
            error_msg = full or data.get("metadata", {}).get("error", "unknown error")
            console.print(f"  [bold red]Error:[/bold red] {error_msg}")
        elif cost > 0:
            tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
            console.print(
                f"[dim]  ${cost:.4f} | {tokens:,} tokens[/dim]"
            )

    elif evt == "agent.thinking.started":
        agent = data.get("agent_id", "agent")
        console.print(f"  [dim]\U0001f9e0 {agent} thinking...[/dim]")

    elif evt == "agent.tool.called":
        agent = data.get("agent_id", "agent")
        tool = data.get("tool_name", data.get("content", ""))
        console.print(f"  [dim]\U0001f527 {agent}: {tool}[/dim]")

    elif evt in ("agent.tool.returned", "user.message.sent",
                 "session.cost.updated", "done"):
        pass  # suppress noise

    else:
        msg = data.get("message", data.get("content", ""))
        if msg:
            console.print(f"  [dim]{evt}: {str(msg)[:80]}[/dim]")


def _render_sse_verbose(event_type: str, data: dict) -> None:
    """Print SSE event as JSONL — no Rich formatting."""
    evt = data.get("event_type", event_type)

    # Skip streaming chunks in verbose mode (aggregated in complete event)
    if evt == "agent.response.chunk":
        return

    print(json.dumps(data, default=str), flush=True)
