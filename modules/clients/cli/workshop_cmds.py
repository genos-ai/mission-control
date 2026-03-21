"""
CLI handler for Workshop commands.

Thin renderer over WorkshopService. Supports running agents,
listing cached inputs, and viewing workshop run history.
"""

import asyncio
import json
import sys

from modules.clients.cli.report import get_console, create_table


def run_workshop(
    cli_logger,
    action: str,
    *,
    agent_name: str | None = None,
    inputs_json: str | None = None,
    prompt_override: str | None = None,
    mission_id: str | None = None,
    limit: int = 20,
    output_format: str = "human",
) -> None:
    """Dispatch workshop CLI actions."""
    actions = {
        "run": _action_run,
        "cached-inputs": _action_cached_inputs,
        "history": _action_history,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(
        cli_logger,
        agent_name=agent_name,
        inputs_json=inputs_json,
        prompt_override=prompt_override,
        mission_id=mission_id,
        limit=limit,
        output_format=output_format,
    ))


async def _action_run(cli_logger, *, agent_name, inputs_json, prompt_override, **_):
    """Run a single agent in workshop mode."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.workshop import WorkshopService

    console = get_console()
    if not agent_name:
        console.print("[red]Agent name is required[/red]")
        sys.exit(1)

    inputs = None
    if inputs_json:
        try:
            inputs = json.loads(inputs_json)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON for --inputs: {e}[/red]")
            sys.exit(1)

    async with get_async_session() as db:
        service = WorkshopService(db)
        result = await service.run_agent(
            agent_name,
            inputs=inputs,
            prompt_override=prompt_override,
        )
        await db.commit()

    console.print(f"\n[bold green]Workshop run completed[/bold green]")
    console.print(f"  Agent: {result['agent_name']}")
    console.print(f"  Cost: ${result['cost_usd']:.4f}")
    console.print(f"  Tokens: {result['input_tokens']} in / {result['output_tokens']} out")
    console.print(f"  Record: {result['execution_record_id']}")

    if result.get("had_prompt_override"):
        console.print("  [yellow]System prompt was overridden[/yellow]")

    output_text = json.dumps(result["output"], indent=2, default=str)
    if len(output_text) > 2000:
        output_text = output_text[:2000] + "\n... (truncated)"
    console.print(f"\n[bold]Output:[/bold]\n{output_text}")


async def _action_cached_inputs(cli_logger, *, agent_name, mission_id, limit, **_):
    """Show cached inputs for an agent."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.workshop import WorkshopService

    console = get_console()
    if not agent_name:
        console.print("[red]Agent name is required[/red]")
        sys.exit(1)

    async with get_async_session() as db:
        service = WorkshopService(db)
        cached = await service.get_cached_inputs(
            agent_name, mission_id=mission_id, limit=limit,
        )

    if not cached:
        console.print(f"[yellow]No cached inputs found for {agent_name}[/yellow]")
        return

    table = create_table(
        f"Cached Inputs — {agent_name}",
        ["ID", "Task", "Cost", "Created"],
    )
    for item in cached:
        table.add_row(
            str(item["task_execution_id"])[:8],
            item["task_id"],
            f"${item['cost_usd']:.4f}" if item["cost_usd"] else "—",
            str(item["created_at"])[:19] if item["created_at"] else "—",
        )
    console.print(table)


async def _action_history(cli_logger, *, agent_name, limit, **_):
    """List workshop run history."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.workshop import WorkshopService

    console = get_console()

    async with get_async_session() as db:
        service = WorkshopService(db)
        runs = await service.list_runs(agent_name=agent_name, limit=limit)

    if not runs:
        console.print("[yellow]No workshop runs found[/yellow]")
        return

    table = create_table(
        "Workshop Runs",
        ["ID", "Agent", "Status", "Cost", "Created"],
    )
    for run in runs:
        table.add_row(
            str(run.id)[:8],
            run.roster_name or "—",
            run.status,
            f"${run.total_cost_usd:.4f}" if run.total_cost_usd else "—",
            str(run.created_at)[:19] if run.created_at else "—",
        )
    console.print(table)
