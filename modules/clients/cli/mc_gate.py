"""Manual-gate CLI commands (Plan 80g).

Thin client over /missions/{mid}/gates/* endpoints. Use when a mission
runs with `gate_mode=manual` and you want to step through each gate
point one at a time.

Typical loop:

    mc run --gate manual <workflow>      # start the run; first gate parks immediately
    mc gate list                         # see what's waiting
    mc gate show <rid>                   # inspect context (full GateContext dump)
    mc gate approve <rid>                # release; next gate parks; repeat
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from modules.clients.cli.api_client import ApiError, CliApiClient
from modules.clients.common.display import build_table, get_console


# =============================================================================
# List
# =============================================================================


async def list_pending(api: CliApiClient, *, mission_id: str) -> None:
    """Print all pending gate requests for the current mission."""
    console = get_console()

    try:
        data = await api.get(f"/missions/{mission_id}/gates/pending")
    except ApiError as exc:
        if exc.status == 404:
            console.print("[dim]Mission has no gates endpoint or no pending gates.[/dim]")
            return
        raise

    gates = data.get("gates", []) if isinstance(data, dict) else []
    if not gates:
        console.print("[dim]No pending gates.[/dim]")
        return

    table = build_table(columns=[
        ("#",        {"justify": "right", "width": 4}),
        ("ID",       {"style": "cyan", "width": 10}),
        ("Gate type",      {"width": 22}),
        ("Created",  {"width": 19}),
        ("Plan",     {"width": 10}),
    ])
    for i, g in enumerate(gates, start=1):
        table.add_row(
            str(i),
            g["id"][:8],
            g.get("gate_type", "?"),
            g.get("created_at", "")[:19],
            (g.get("plan_id") or "—")[:8],
        )
    console.print(f"[bold]{len(gates)} pending gate(s)[/bold]")
    console.print(table)


# =============================================================================
# Show
# =============================================================================


async def show(api: CliApiClient, *, mission_id: str, request_id: str) -> None:
    """Print full context for one gate request."""
    console = get_console()
    resolved = await _resolve_gate_id(api, mission_id, request_id)
    data = await api.get(f"/missions/{mission_id}/gates/{resolved}")
    console.print(f"[bold]Gate {resolved[:8]}[/bold]  "
                  f"type=[cyan]{data.get('gate_type','?')}[/cyan]  "
                  f"status={data.get('status','?')}  "
                  f"created={data.get('created_at','')[:19]}")
    if data.get("decided_at"):
        console.print(f"  decided={data['decided_at'][:19]}  "
                      f"decision={data.get('decision_json', {})}")
    if data.get("timed_out_at"):
        console.print(f"  timed_out={data['timed_out_at'][:19]}")
    console.print("\n[bold]Context:[/bold]")
    console.print(json.dumps(data.get("context_json", {}), indent=2, default=str))


# =============================================================================
# Decide  (approve / reject / skip / retry / abort)
# =============================================================================


async def decide(
    api: CliApiClient,
    *,
    mission_id: str,
    request_id: str,
    action: str,
    reason: str | None,
) -> None:
    """POST a decision for one gate. Wakes the blocked dispatcher."""
    console = get_console()
    resolved = await _resolve_gate_id(api, mission_id, request_id)
    body: dict[str, Any] = {"action": action}
    if reason:
        body["reason"] = reason
    await api.post(
        f"/missions/{mission_id}/gates/{resolved}/decide",
        body=body,
    )
    console.print(
        f"[green]Decided[/green] {resolved[:8]}  action=[cyan]{action}[/cyan]"
        + (f"  reason={reason!r}" if reason else "")
    )


# =============================================================================
# Helpers
# =============================================================================


async def _resolve_gate_id(
    api: CliApiClient, mission_id: str, gate_id: str,
) -> str:
    """Accept full UUID or unique ≥4-char prefix, matched against pending gates."""
    if len(gate_id) >= 32 and "-" in gate_id:
        return gate_id
    if len(gate_id) < 4:
        click.echo(f"Gate id prefix '{gate_id}' too short (need ≥ 4 chars).", err=True)
        sys.exit(1)
    data = await api.get(f"/missions/{mission_id}/gates/pending")
    gates = data.get("gates", []) if isinstance(data, dict) else []
    matches = [g["id"] for g in gates if g["id"].startswith(gate_id)]
    if not matches:
        click.echo(
            f"No pending gate id starts with '{gate_id}'. "
            "Use `mc gate list` to see what's waiting.",
            err=True,
        )
        sys.exit(1)
    if len(matches) > 1:
        click.echo(
            f"Ambiguous prefix '{gate_id}' matches {len(matches)} gates:\n  "
            + "\n  ".join(matches),
            err=True,
        )
        sys.exit(1)
    return matches[0]
