"""Mission schedule CLI renderer (Plan 88 step 88.1.13, contracts 3.5.4).

`mc schedule` manages a mission's recurring schedules through the REST API
only. A schedule is addressed by its name, resolved with an exact match over
`GET /missions/{id}/schedules?include_archived=true`. A schedule runs either an
objective template or a saved workflow; `--workflow NAME` is resolved through
`GET /missions/{id}/workflows`. Zero backend-service imports.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, NoReturn

import click

from modules.clients.cli.api_client import CliApiClient
from modules.clients.cli.report import build_table, get_console

_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# =============================================================================
# Presentation parsing
# =============================================================================


def parse_duration(value: str | None) -> int | None:
    """`90s`, `15m`, `6h` or `2d` to seconds; None passes through."""
    if value is None:
        return None
    match = _DURATION.match(value.strip())
    if match is None:
        raise click.BadParameter(f"{value!r} is not a duration like 90s, 15m, 6h or 2d")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def parse_params(items: tuple[str, ...]) -> dict[str, str]:
    """Repeated `k=v` options to a dict."""
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise click.BadParameter(f"{item!r} is not key=value", param_hint="--param")
        key, value = item.split("=", 1)
        params[key] = value
    return params


# =============================================================================
# Commands
# =============================================================================


async def list_schedules(
    api: CliApiClient, *, mission_id: str, include_archived: bool, as_json: bool
) -> None:
    """Print the mission's schedules."""
    data = await api.get(
        f"/missions/{mission_id}/schedules",
        params={"include_archived": str(include_archived).lower()},
    )
    schedules = data.get("schedules", []) if isinstance(data, dict) else []
    console = get_console()
    if as_json:
        console.print(json.dumps(data, indent=2, default=str))
        return
    if not schedules:
        console.print("[dim]No schedules. Create one with `mc schedule create`.[/dim]")
        return

    table = build_table(
        "Mission Schedules",
        columns=[
            ("Name", {"style": "cyan", "width": 24}),
            ("Status", {"width": 10}),
            ("Kind", {"width": 20}),
            ("Cron", {"width": 16}),
            ("Time zone", {"width": 20}),
            ("Runs", {"justify": "right", "width": 8}),
            ("Sync", {"width": 8}),
        ],
    )
    for s in schedules:
        runs = str(s.get("executed_run_count", 0))
        if s.get("max_runs"):
            runs += f"/{s['max_runs']}"
        table.add_row(
            s.get("name", ""),
            s.get("status", ""),
            s.get("kind", ""),
            s.get("cron_expression", ""),
            s.get("time_zone_name", ""),
            runs,
            _sync_label(s),
        )
    console.print(table)


async def show_schedule(api: CliApiClient, *, mission_id: str, name: str) -> None:
    """Print one schedule with its next fire times and Temporal sync state."""
    sid = (await resolve_schedule(api, mission_id, name))["id"]
    s = await api.get(f"/missions/{mission_id}/schedules/{sid}")
    console = get_console()
    console.print(f"[bold]Schedule {s.get('name')}[/bold]  status=[cyan]{s.get('status')}[/cyan]")
    rows = [
        ("id", s.get("id")),
        ("kind", s.get("kind")),
        ("objective", s.get("objective_template")),
        ("workflow", s.get("workflow_definition_id")),
        ("parameters", s.get("workflow_parameters") or None),
        ("cron", s.get("cron_expression")),
        ("time zone", s.get("time_zone_name")),
        ("starts at", s.get("starts_at")),
        ("ends at", s.get("ends_at")),
        (
            "runs",
            f"{s.get('executed_run_count', 0)}/{s.get('max_runs') or 'unlimited'}",
        ),
        ("catch-up", f"{s.get('catch_up_window_seconds')}s"),
        ("completed", s.get("completed_reason")),
        ("temporal id", s.get("temporal_schedule_id")),
    ]
    for label, value in rows:
        if value is not None:
            console.print(f"  {label + ':':14}{value}")
    console.print(f"  {'sync:':14}{_sync_label(s)}")
    if s.get("temporal_sync_state") == "failed":
        console.print(f"  [red]{s.get('temporal_sync_error') or 'sync failed'}[/red]")
    fire_times = s.get("next_fire_times") or []
    console.print("\n[bold]Next fire times:[/bold]")
    if not fire_times:
        console.print("  [dim]none[/dim]")
    for fire_time in fire_times:
        console.print(f"  {fire_time}")


async def create_schedule(
    api: CliApiClient, *, mission_id: str, name: str, fields: dict[str, Any]
) -> None:
    """POST a new schedule built from the CLI flags."""
    body = await _build_body(api, mission_id, fields)
    body["name"] = name
    if body.get("objective_template") is not None:
        body["kind"] = "objective"
    elif body.get("workflow_definition_id") is not None:
        body["kind"] = "workflow_definition"
    else:
        _fail("Pass --objective TEXT or --workflow NAME.")
    s = await api.post(f"/missions/{mission_id}/schedules", body=body)
    _print_result("created", s)


async def edit_schedule(
    api: CliApiClient, *, mission_id: str, name: str, fields: dict[str, Any]
) -> None:
    """PATCH the named schedule with only the flags given."""
    sid = (await resolve_schedule(api, mission_id, name))["id"]
    body = await _build_body(api, mission_id, fields)
    if not body:
        _fail("Nothing to change. Pass at least one flag.")
    s = await api.patch(f"/missions/{mission_id}/schedules/{sid}", body=body)
    _print_result("updated", s)


async def change_status(api: CliApiClient, *, mission_id: str, name: str, action: str) -> None:
    """Pause, resume or delete (archive) the named schedule."""
    sid = (await resolve_schedule(api, mission_id, name))["id"]
    path = f"/missions/{mission_id}/schedules/{sid}"
    if action == "delete":
        s = await api.delete(path)
        _print_result("deleted", s)
        return
    s = await api.post(f"{path}/{action}")
    _print_result(f"{action}d", s)


# =============================================================================
# Resolution helpers
# =============================================================================


async def resolve_schedule(api: CliApiClient, mission_id: str, name: str) -> dict[str, Any]:
    """The schedule whose name matches exactly, archived included; exit 1 when none."""
    data = await api.get(f"/missions/{mission_id}/schedules", params={"include_archived": "true"})
    for s in data.get("schedules", []) if isinstance(data, dict) else []:
        if s.get("name") == name:
            return s
    _fail(f"Schedule '{name}' not found")


async def resolve_workflow(api: CliApiClient, mission_id: str, name: str) -> str:
    """The mission workflow definition id whose name matches exactly; exit 1 when none."""
    data = await api.get(f"/missions/{mission_id}/workflows")
    for w in data.get("workflows", []) if isinstance(data, dict) else []:
        if w.get("name") == name:
            return w["id"]
    _fail(f"Workflow '{name}' not found in this mission")


async def _build_body(api: CliApiClient, mission_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Map CLI flags to a create/update body, leaving out flags that were not given."""
    body: dict[str, Any] = {}
    if fields.get("objective") is not None and fields.get("workflow") is not None:
        _fail("Pass either --objective or --workflow, not both.")
    if fields.get("objective") is not None:
        body["objective_template"] = fields["objective"]
    if fields.get("workflow") is not None:
        body["workflow_definition_id"] = await resolve_workflow(api, mission_id, fields["workflow"])
    if fields.get("params"):
        body["workflow_parameters"] = fields["params"]
    for flag, key in (
        ("cron", "cron_expression"),
        ("tz", "time_zone_name"),
        ("starts_at", "starts_at"),
        ("ends_at", "ends_at"),
        ("max_runs", "max_runs"),
        ("catch_up_window_seconds", "catch_up_window_seconds"),
    ):
        if fields.get(flag) is not None:
            body[key] = fields[flag]
    return body


def _sync_label(s: dict[str, Any]) -> str:
    state = s.get("temporal_sync_state") or ""
    return f"[red]{state}[/red]" if state == "failed" else state


def _print_result(verb: str, s: dict[str, Any]) -> None:
    get_console().print(
        f"[green]Schedule {verb}:[/green] [cyan]{s.get('name')}[/cyan]  "
        f"status={s.get('status')}  sync={_sync_label(s)}"
    )


def _fail(message: str) -> NoReturn:
    get_console().print(f"[red]{message}[/red]")
    sys.exit(1)
