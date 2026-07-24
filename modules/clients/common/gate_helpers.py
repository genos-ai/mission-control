"""
Shared gate display helpers for CLI, TUI, and any future client.

These functions render gate-related information (cost colors, status
icons, headers) and are used by both CliGateReviewer and TuiGateReviewer.

No module-level backend imports — safe for thin CLI usage.
"""

from __future__ import annotations


def cost_color(cost: float, budget: float) -> str:
    """Return Rich color name based on cost-to-budget ratio."""
    if budget <= 0:
        return "white"
    ratio = cost / budget
    if ratio > 0.9:
        return "red"
    if ratio > 0.6:
        return "yellow"
    return "green"


def status_icon(status: str) -> str:
    """Return Rich-markup status icon for verification/task status."""
    return {
        "success": "[green]\u2713[/green]",
        "failed": "[red]\u2717[/red]",
        "timeout": "[yellow]\u23f1[/yellow]",
        "skipped": "[dim]\u2014[/dim]",
    }.get(status, f"[dim]{status}[/dim]")


# Action label colors — shared by CLI and TUI gate reviewers.
ACTION_COLORS: dict[str, str] = {
    "continue": "green",
    "skip": "yellow",
    "retry": "cyan",
    "abort": "red",
    "modify": "magenta",
}


def safe_css_id(raw: str) -> str:
    """Sanitise a string for use as a Textual CSS ID fragment."""
    return raw.replace(".", "-").replace("_", "-")


# ── Status icons (shared by mission panel, workflow, history) ─────

STATUS_ICONS: dict[str, str] = {
    "active": "[green]●[/green]",
    "inactive": "[dim]○[/dim]",
    "archived": "[dim]⊘[/dim]",
    "pending": "[dim]○[/dim]",
    "proposed": "[dim]○[/dim]",
    "queued": "[blue]○[/blue]",
    "approved": "[cyan]○[/cyan]",
    "running": "[bold cyan]●[/bold cyan]",
    "success": "[green]✓[/green]",
    "completed": "[green]✓[/green]",
    "failed": "[red]✗[/red]",
    "timeout": "[yellow]⏱[/yellow]",
    "timed_out": "[yellow]⏱[/yellow]",
    "skipped": "[dim]⊘[/dim]",
    "cancelled": "[yellow]⊘[/yellow]",
}


def filter_catalog_agents(
    agents: list[dict],
    query: str,
) -> list[dict]:
    """Filter catalog agent dicts by name, description, or keywords."""
    q = query.lower().strip()
    if not q:
        return agents
    return [
        a
        for a in agents
        if q in a.get("agent_name", "").lower()
        or q in a.get("description", "").lower()
        or any(q in k.lower() for k in a.get("keywords", []))
    ]


# GateContext is duck-typed here (string annotation) — this module deliberately has no
# backend imports (see module docstring), so the type is never actually imported.
def gate_header(ctx: "GateContext", title: str) -> str:  # noqa: F821
    """Format a gate panel header with title, mission ID, and cost."""
    cc = cost_color(ctx.total_cost_usd, ctx.budget_usd)
    return (
        f"[bold]{title}[/bold]  |  "
        f"Mission: {ctx.mission_id[:16]}  |  "
        f"Cost: [{cc}]${ctx.total_cost_usd:.4f}[/{cc}]"
        f" / ${ctx.budget_usd:.2f}"
    )
