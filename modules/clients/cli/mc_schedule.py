"""Recurring workflow schedule CLI (Plan 83).

`mc schedule` is the end-user surface for cron-based scheduling of a
mission's **defined workflows**. It is a strict thin client: every
command goes through the REST API via `CliApiClient` — there are zero
backend-service imports here (contrast `schedule_cmds.py`, the admin-only
service-based renderer, which must NOT be reused from `mc.py`).

The scheduled unit is a `workflow_definition_id`; scheduling a free-form
mission objective is a separate, out-of-scope path (Plan 83 §8).

Commands:
    mc schedule                 # list schedules for the current mission
    mc schedule list            # same as above
    mc schedule create --workflow <id> --cron "0 9 * * *"
    mc schedule enable <schedule_id>
    mc schedule disable <schedule_id>
    mc schedule delete <schedule_id>
"""

from __future__ import annotations

import json
import sys
from typing import Any

from modules.clients.cli.api_client import ApiError, CliApiClient, resolve_short_id
from modules.clients.common.display import build_table, get_console

# =============================================================================
# list — schedules for the current mission
# =============================================================================


async def list_schedules(
    api: CliApiClient,
    *,
    mission_id: str,
    output_format: str = "human",
) -> None:
    """List every schedule (enabled and disabled) for the current mission."""
    console = get_console()
    try:
        data = await api.get(
            f"/missions/{mission_id}/schedules",
            params={"enabled_only": "false"},
        )
    except ApiError as exc:
        _fail(exc)

    schedules = data.get("schedules", []) if isinstance(data, dict) else []

    if output_format == "json":
        console.print(json.dumps(data, indent=2, default=str))
        return

    if not schedules:
        console.print("[dim]No schedules. Create one with `mc schedule create`.[/dim]")
        return

    table = build_table(
        "Workflow Schedules",
        columns=[
            ("ID", {"style": "cyan", "width": 38}),
            ("Enabled", {"width": 9}),
            ("Cron", {"width": 18}),
            ("Workflow", {"width": 38}),
            ("Iterations", {"width": 12}),
            ("Next Fire", {"width": 20}),
            ("Description", {"ratio": 1, "no_wrap": False}),
        ],
    )
    for s in schedules:
        enabled = "[green]yes[/green]" if s.get("enabled") else "[red]no[/red]"
        iters = str(s.get("iteration_count", 0))
        if s.get("max_iterations"):
            iters += f"/{s['max_iterations']}"
        next_fire = (s.get("next_fire_at") or "—")[:19]
        table.add_row(
            s.get("id", "?"),
            enabled,
            s.get("cron_expression", "?"),
            s.get("workflow_definition_id", "?"),
            iters,
            next_fire,
            s.get("description", ""),
        )
    console.print(table)


# =============================================================================
# create — new cron schedule for a workflow
# =============================================================================


async def create_schedule(
    api: CliApiClient,
    *,
    mission_id: str,
    workflow: str,
    cron: str,
    description: str,
    budget: float | None,
    max_iterations: int | None,
    cooldown: int,
) -> None:
    """Create a cron schedule bound to a workflow definition.

    Builds a `WorkflowScheduleCreateRequest`-shaped payload and omits keys
    whose value is ``None`` (the backend schema is ``extra="forbid"`` — do
    not send nulls for optional numeric fields).
    """
    console = get_console()
    payload: dict[str, Any] = {
        "workflow_definition_id": workflow,
        "cron_expression": cron,
        "cooldown_seconds": cooldown,
    }
    if description:
        payload["description"] = description
    if budget is not None:
        payload["budget_per_run_usd"] = budget
    if max_iterations is not None:
        payload["max_iterations"] = max_iterations

    try:
        schedule = await api.post(
            f"/missions/{mission_id}/schedules",
            body=payload,
        )
    except ApiError as exc:
        _fail(exc)

    console.print(f"[green]Schedule created:[/green] [cyan]{schedule.get('id')}[/cyan]")
    console.print(f"  Cron:      {schedule.get('cron_expression')}")
    console.print(f"  Next fire: {schedule.get('next_fire_at') or '—'}")


# =============================================================================
# enable / disable — toggle a schedule
# =============================================================================


async def set_enabled(
    api: CliApiClient,
    *,
    mission_id: str,
    schedule_id: str,
    enabled: bool,
) -> None:
    """Enable or disable a schedule by id (accepts a short prefix)."""
    console = get_console()
    sid = await _resolve_schedule_id(api, mission_id, schedule_id)
    try:
        await api.patch(
            f"/missions/{mission_id}/schedules/{sid}",
            body={"enabled": enabled},
        )
    except ApiError as exc:
        _fail(exc)
    state = "enabled" if enabled else "disabled"
    console.print(f"[green]Schedule {state}:[/green] [cyan]{sid}[/cyan]")


# =============================================================================
# delete — remove a schedule
# =============================================================================


async def delete_schedule(
    api: CliApiClient,
    *,
    mission_id: str,
    schedule_id: str,
) -> None:
    """Delete a schedule by id (accepts a short prefix)."""
    console = get_console()
    sid = await _resolve_schedule_id(api, mission_id, schedule_id)
    try:
        await api.delete(f"/missions/{mission_id}/schedules/{sid}")
    except ApiError as exc:
        _fail(exc)
    console.print(f"[green]Schedule deleted:[/green] [cyan]{sid}[/cyan]")


# =============================================================================
# Helpers
# =============================================================================


async def _resolve_schedule_id(
    api: CliApiClient,
    mission_id: str,
    prefix: str,
) -> str:
    """Accept a full UUID or unique >=4-char prefix, matched against schedules."""
    return await resolve_short_id(
        api,
        list_url=f"/missions/{mission_id}/schedules?enabled_only=false",
        list_field="schedules",
        prefix=prefix,
        not_found_hint="Run `mc schedule list` to see ids.",
    )


def _fail(exc: ApiError) -> None:
    """Print a red, actionable message and exit (rule 002.3 / 014 — no swallow)."""
    get_console().print(f"[red]Schedule request failed:[/red] {exc}")
    sys.exit(1)
