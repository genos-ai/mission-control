"""Gate configuration + post-execution decision CLI (Plan 80h).

After the unification of pre-execution approval into the task lifecycle,
`mc gate` is the surface for:

- **Gate configuration** — set / view the current gate mode for this
  mission's plan. The mode determines who approves task transitions.
- **Post-execution gate decisions** — for the (rare) post_task,
  verification_failed, post_layer, post_run gates that fire when an
  agent's output needs review or the supervisor needs to pick a next
  move. These are NOT used for routine pre-execution approval — for
  that, use `mc plan approve`.

Commands:
    mc gate                  # show current mode + any pending gates
    mc gate show             # same as above
    mc gate set <mode>       # change the gate mode
    mc gate modes            # list available modes
    mc gate pending          # list pending post-execution gates
    mc gate decide <id> <action>  # decide a post-execution gate
"""

from __future__ import annotations

import json
from typing import Any

from modules.clients.cli.api_client import ApiError, CliApiClient, resolve_short_id
from modules.clients.common.display import build_table, get_console


# =============================================================================
# Mode metadata
# =============================================================================


VALID_MODES: dict[str, str] = {
    "autonomous": "LLM (or rule engine) approves everything; no human pause.",
    "manual":     "Human approves each step via `mc plan approve <task_id>` (HTTP API).",
    "interactive": "Human approves each step at a Rich CLI prompt (TTY-bound).",
    "ai_assisted": "LLM recommends; human confirms at a TTY prompt.",
}


VALID_ACTIONS_BY_GATE: dict[str, list[str]] = {
    # Standard post-execution gates.
    "post_task":          ["continue", "skip", "retry", "abort"],
    "verification_failed": ["continue", "skip", "retry", "abort"],
    "post_layer":         ["continue", "abort"],
    # Supervisor / autonomy-loop decision points.
    "post_run":           [
        "wait", "advance_approved", "advance_refine",
        "propose_complete", "escalate",
    ],
}


# =============================================================================
# show — current mode + pending gates
# =============================================================================


async def show(api: CliApiClient, *, mission_id: str) -> None:
    """Print current gate mode and any pending post-execution gates."""
    console = get_console()

    # Current mode from the plan.
    try:
        plan = await api.get(f"/missions/{mission_id}/plan")
        mode = plan.get("gate_mode") or "autonomous"
    except ApiError as exc:
        if exc.status == 404:
            mode = "(no plan yet)"
        else:
            raise

    console.print(f"[bold]Gate mode:[/bold] [cyan]{mode}[/cyan]")
    if mode in VALID_MODES:
        console.print(f"  [dim]{VALID_MODES[mode]}[/dim]")

    # Pending post-execution gates.
    try:
        data = await api.get(f"/missions/{mission_id}/gates/pending")
    except ApiError as exc:
        if exc.status == 404:
            return
        raise
    gates = data.get("gates", []) if isinstance(data, dict) else []
    if not gates:
        console.print("\n[dim]No pending post-execution gates.[/dim]")
        return

    console.print(f"\n[bold]{len(gates)} pending gate(s):[/bold]")
    table = build_table(columns=[
        ("#",         {"justify": "right", "width": 4}),
        ("ID",        {"style": "cyan", "width": 38}),
        ("Gate type", {"width": 22}),
        ("Created",   {"width": 19}),
    ])
    for i, g in enumerate(gates, start=1):
        table.add_row(
            str(i),
            g["id"],
            g.get("gate_type", "?"),
            g.get("created_at", "")[:19],
        )
    console.print(table)


# =============================================================================
# set — change the gate mode
# =============================================================================


async def set_mode(api: CliApiClient, *, mission_id: str, mode: str) -> None:
    """Change the gate mode for this mission's plan."""
    console = get_console()
    if mode not in VALID_MODES:
        console.print(
            f"[red]Invalid mode '{mode}'. Valid: {', '.join(sorted(VALID_MODES))}.[/red]"
        )
        return
    await api.patch(f"/missions/{mission_id}/plan", body={"gate_mode": mode})
    console.print(f"[green]Gate mode set:[/green] [cyan]{mode}[/cyan]")
    console.print(f"  [dim]{VALID_MODES[mode]}[/dim]")


# =============================================================================
# modes — list available modes
# =============================================================================


async def list_modes(api: CliApiClient) -> None:
    """List the four supported gate modes with one-line descriptions."""
    console = get_console()
    console.print("[bold]Available gate modes:[/bold]\n")
    for mode in sorted(VALID_MODES):
        console.print(f"  [cyan]{mode}[/cyan]")
        console.print(f"      [dim]{VALID_MODES[mode]}[/dim]\n")


# =============================================================================
# pending — list pending post-execution gates
# =============================================================================


async def pending(api: CliApiClient, *, mission_id: str) -> None:
    """Print pending post-execution gates only (not pre-execution / task approvals)."""
    console = get_console()
    try:
        data = await api.get(f"/missions/{mission_id}/gates/pending")
    except ApiError as exc:
        if exc.status == 404:
            console.print("[dim]No gates endpoint or mission not found.[/dim]")
            return
        raise

    gates = data.get("gates", []) if isinstance(data, dict) else []
    if not gates:
        console.print(
            "[dim]No pending post-execution gates.[/dim]\n"
            "[dim]For task approvals, use `mc plan show --status proposed`.[/dim]"
        )
        return

    table = build_table(columns=[
        ("#",         {"justify": "right", "width": 4}),
        ("ID",        {"style": "cyan", "width": 38}),
        ("Gate type", {"width": 22}),
        ("Created",   {"width": 19}),
        ("Valid actions", {"ratio": 1, "no_wrap": False}),
    ])
    for i, g in enumerate(gates, start=1):
        gt = g.get("gate_type", "?")
        actions = ", ".join(VALID_ACTIONS_BY_GATE.get(gt, ["?"]))
        table.add_row(
            str(i),
            g["id"],
            gt,
            g.get("created_at", "")[:19],
            actions,
        )
    console.print(f"[bold]{len(gates)} pending post-execution gate(s):[/bold]")
    console.print(table)


# =============================================================================
# decide — submit a post-execution gate decision
# =============================================================================


async def decide(
    api: CliApiClient,
    *,
    mission_id: str,
    gate_id: str,
    action: str,
    reason: str | None,
) -> None:
    """POST a decision for one post-execution gate."""
    console = get_console()
    resolved = await _resolve_gate_id(api, mission_id, gate_id)
    body: dict[str, Any] = {"action": action}
    if reason:
        body["reason"] = reason
    await api.post(
        f"/missions/{mission_id}/gates/{resolved}/decide",
        body=body,
    )
    console.print(
        f"[green]Decided[/green] {resolved}  action=[cyan]{action}[/cyan]"
        + (f"  reason={reason!r}" if reason else "")
    )


# =============================================================================
# Helpers
# =============================================================================


async def _resolve_gate_id(
    api: CliApiClient, mission_id: str, gate_id: str,
) -> str:
    """Accept full UUID or unique ≥4-char prefix, matched against pending gates."""
    return await resolve_short_id(
        api,
        list_url=f"/missions/{mission_id}/gates/pending",
        list_field="gates",
        prefix=gate_id,
        not_found_hint="Use `mc gate pending` to see what's waiting.",
    )
