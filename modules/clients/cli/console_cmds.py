"""
CLI handler for console monitor command.

Rich Live dashboard showing missions, recent runs, agent status,
and system metrics. Inspired by Zeblit's console monitor pattern.

Usage:
    python admin.py console monitor
    python admin.py console monitor --view developer
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from modules.backend.core.logging import get_logger
from modules.clients.common.display import get_console, status_color
from modules.clients.common.gate_helpers import STATUS_ICONS

logger = get_logger(__name__)


# ── Data fetching ──────────────────────────────────────────────────────


async def _fetch_missions() -> list[dict]:
    from modules.backend.services.mission import MissionService

    async with MissionService.factory() as svc:
        missions = await svc.list_missions()
        return [
            {
                "id": str(m.id),
                "name": m.name,
                "status": m.status.value if hasattr(m.status, "value") else str(m.status),
            }
            for m in missions
        ]


async def _fetch_recent_runs(limit: int = 10) -> list[dict]:
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        records, _total = await svc.list_executions(limit=limit, offset=0)
        return [
            {
                "id": str(getattr(r, "id", "")),
                "objective": getattr(r, "objective_statement", "") or getattr(r, "objective", "") or "(no objective)",
                "status": r.status.value if hasattr(r.status, "value") else str(getattr(r, "status", "?")),
                "cost": getattr(r, "total_cost_usd", 0.0) or 0.0,
                "roster": getattr(r, "roster_name", "") or "",
                "created_at": str(getattr(r, "created_at", "")),
                "input_tokens": getattr(r, "input_tokens", 0) or 0,
                "output_tokens": getattr(r, "output_tokens", 0) or 0,
            }
            for r in records
        ]


async def _fetch_catalog_summary() -> dict:
    from modules.backend.services.agent_catalog import AgentCatalogService

    async with AgentCatalogService.factory() as svc:
        agents = await svc.list_catalog(enabled_only=False)
        enabled = sum(1 for a in agents if a.enabled)
        return {
            "total": len(agents),
            "enabled": enabled,
            "agents": [
                {
                    "name": a.agent_name,
                    "type": a.agent_type,
                    "enabled": a.enabled,
                }
                for a in agents
            ],
        }


async def _fetch_health() -> dict:
    from modules.backend.services.health import HealthCheckService

    try:
        async with HealthCheckService.factory() as svc:
            report = await svc.check_health()
            return {
                "overall": report.overall_status,
                "components": [
                    {
                        "name": c.name,
                        "status": c.status,
                        "latency_ms": c.latency_ms,
                    }
                    for c in report.components
                ],
            }
    except Exception:
        return {"overall": "unknown", "components": []}


# ── Display builders ───────────────────────────────────────────────────


def _create_user_display(
    missions: list[dict],
    runs: list[dict],
    catalog: dict,
    health: dict,
) -> Layout:
    """Build the user-friendly Rich Layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )

    # ── Header ─────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")
    total_cost = sum(r.get("cost", 0) for r in runs)
    layout["header"].update(Panel(
        f"[bold cyan]Mission Control[/bold cyan]  |  "
        f"{now}  |  "
        f"[green]{len(missions)} missions[/green]  |  "
        f"[yellow]{len(runs)} recent runs[/yellow]  |  "
        f"Cost: [bold]${total_cost:.2f}[/bold]",
    ))

    # ── Main: activity (left) + status (right) ─────────────
    layout["main"].split_row(
        Layout(name="activity", ratio=2),
        Layout(name="status", ratio=1),
    )

    # Activity: recent runs table
    table = Table(
        show_header=True, header_style="bold blue",
        box=box.SIMPLE_HEAVY, expand=True,
    )
    table.add_column("Status", width=3, no_wrap=True)
    table.add_column("Objective", ratio=1)
    table.add_column("Roster", width=12, style="dim")
    table.add_column("Cost", width=8, justify="right")
    table.add_column("When", width=16, style="dim")

    for r in runs[:12]:
        status = r.get("status", "?")
        icon = STATUS_ICONS.get(status, "?").replace("[", "\\[") if "[" not in STATUS_ICONS.get(status, "?") else STATUS_ICONS.get(status, "?")
        # Plain icons for Rich table (no Textual markup)
        status_sym = {"completed": "[green]✓[/green]", "success": "[green]✓[/green]",
                      "failed": "[red]✗[/red]", "running": "[cyan]●[/cyan]",
                      "pending": "[dim]○[/dim]"}.get(status, status)
        obj = (r.get("objective", "") or "")[:50]
        cost = f"${r.get('cost', 0):.2f}"
        when = r.get("created_at", "")[:16]
        roster = r.get("roster", "")
        table.add_row(status_sym, obj, roster, cost, when)

    layout["activity"].update(Panel(
        table, title="Recent Runs", border_style="blue",
    ))

    # Status panel
    lines: list[str] = []

    # Missions
    lines.append("[bold green]Missions[/bold green]")
    for m in missions[:5]:
        status = m.get("status", "?")
        lines.append(f"  [green]●[/green] {m['name']}  [dim]{status}[/dim]")
    lines.append("")

    # Agents
    lines.append(f"[bold cyan]Agents[/bold cyan]  ({catalog.get('enabled', 0)}/{catalog.get('total', 0)} enabled)")
    for a in catalog.get("agents", [])[:6]:
        indicator = "[green]●[/green]" if a["enabled"] else "[dim]○[/dim]"
        lines.append(f"  {indicator} {a['name']}  [dim]{a['type']}[/dim]")
    lines.append("")

    # Health
    overall = health.get("overall", "unknown")
    h_color = "green" if overall == "healthy" else "red"
    lines.append(f"[bold {h_color}]Health: {overall}[/bold {h_color}]")
    for c in health.get("components", []):
        c_color = "green" if c["status"] == "healthy" else "red"
        latency = f"  {c['latency_ms']}ms" if c.get("latency_ms") else ""
        lines.append(f"  [{c_color}]●[/{c_color}] {c['name']}{latency}")

    layout["status"].update(Panel(
        "\n".join(lines), title="System Status", border_style="green",
    ))

    # ── Footer ─────────────────────────────────────────────
    layout["footer"].update(Panel(
        "[dim]Press Ctrl+C to exit  |  "
        "Use --view developer for technical details  |  "
        "Use python tui.py for the full interactive TUI[/dim]",
    ))

    return layout


def _create_developer_display(
    missions: list[dict],
    runs: list[dict],
    catalog: dict,
) -> Panel:
    """Build the developer-focused table with technical details."""
    table = Table(
        show_header=True, header_style="bold blue",
        box=box.SIMPLE_HEAVY, expand=True,
    )
    table.add_column("Status", width=3, no_wrap=True)
    table.add_column("ID", width=8, style="dim")
    table.add_column("Objective", ratio=1)
    table.add_column("Roster", width=12, style="dim")
    table.add_column("Tokens", width=20, style="green")
    table.add_column("Cost", width=8, justify="right")
    table.add_column("Created", width=16, style="dim")

    for r in runs[:15]:
        status = r.get("status", "?")
        status_sym = {"completed": "[green]✓[/green]", "success": "[green]✓[/green]",
                      "failed": "[red]✗[/red]", "running": "[cyan]●[/cyan]",
                      "pending": "[dim]○[/dim]"}.get(status, status)
        rid = r.get("id", "")[:8]
        obj = (r.get("objective", "") or "")[:40]
        cost = f"${r.get('cost', 0):.4f}"
        when = r.get("created_at", "")[:16]
        roster = r.get("roster", "")
        in_tok = r.get("input_tokens", 0)
        out_tok = r.get("output_tokens", 0)
        tokens = f"{in_tok:,} in / {out_tok:,} out"
        table.add_row(status_sym, rid, obj, roster, tokens, cost, when)

    now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")
    total_cost = sum(r.get("cost", 0) for r in runs)
    subtitle = (
        f"{now}  |  {len(missions)} missions  |  "
        f"{catalog.get('enabled', 0)} agents  |  "
        f"Total: ${total_cost:.4f}"
    )

    return Panel(
        table,
        title="Mission Control — Developer Console",
        subtitle=f"[dim]{subtitle}[/dim]",
        border_style="blue",
    )


# ── Entry points ───────────────────────────────────────────────────────


async def _monitor_loop(view: str, refresh: float) -> None:
    """Main polling loop for console monitor."""
    console = get_console()

    with Live(console=console, refresh_per_second=2, vertical_overflow="crop") as live:
        while True:
            try:
                missions = await _fetch_missions()
                runs = await _fetch_recent_runs(limit=15)
                catalog = await _fetch_catalog_summary()

                if view == "developer":
                    display = _create_developer_display(missions, runs, catalog)
                else:
                    health = await _fetch_health()
                    display = _create_user_display(missions, runs, catalog, health)

                live.update(display)
                await asyncio.sleep(refresh)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.warning("Console monitor error", exc_info=True)
                console.print(f"[red]Error: {e}[/red]")
                break


def run_monitor(view: str = "user", refresh: float = 2.0) -> None:
    """Run the console monitor (called from admin.py)."""
    console = get_console()
    console.print(
        f"[bold cyan]Mission Control Console[/bold cyan]  |  "
        f"View: [bold]{view}[/bold]  |  "
        f"Refresh: {refresh}s",
    )
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")

    try:
        asyncio.run(_monitor_loop(view, refresh))
    except KeyboardInterrupt:
        console.print("\n[yellow]Console monitor stopped.[/yellow]")
