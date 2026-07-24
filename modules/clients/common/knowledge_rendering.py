"""
Knowledge display primitives for CLI and TUI.

All functions build Rich renderables — no business logic (thin client).
Uses get_console() from display.py.
"""

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def render_intent(intent: dict) -> Panel:
    """Render a single intent revision as a Rich Panel."""
    scope = intent.get("scope", {})
    scope_in = scope.get("in", [])
    scope_out = scope.get("out", [])

    body = Text()
    body.append(intent.get("intent", ""), style="bold")
    body.append("\n")

    if scope_in:
        body.append("\nIn scope: ", style="green")
        body.append(", ".join(scope_in))
    if scope_out:
        body.append("\nOut of scope: ", style="red")
        body.append(", ".join(scope_out))

    body.append(f"\n\nSource: {intent.get('source', '?')}")
    body.append(f"  |  Reason: {intent.get('reason', '?')}")
    body.append(f"\nCreated: {intent.get('created_at', '?')}")

    return Panel(
        body,
        title=f"[bold]Intent[/bold] — {intent.get('intent_summary', '?')}",
        border_style="yellow",
        box=box.ROUNDED,
    )


def render_intent_history(revisions: list[dict]) -> Table:
    """Render intent revision timeline as a Rich Table."""
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        title="Intent History",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Summary", min_width=30)
    table.add_column("Source", width=12)
    table.add_column("Reason", min_width=20)
    table.add_column("Date", width=20)

    for i, rev in enumerate(revisions, 1):
        table.add_row(
            str(i),
            rev.get("intent_summary", "?"),
            rev.get("source", "?"),
            rev.get("reason", "?")[:60],
            rev.get("created_at", "?")[:19],
        )

    return table


def render_learning_card(learning: dict) -> Panel:
    """Render a single learning as a Rich Panel."""
    kind = learning.get("kind", "?")
    title = learning.get("title", "?")
    confidence = learning.get("confidence", 0)
    count = learning.get("occurrence_count", 1)
    promoted = learning.get("platform_promoted", False)

    kind_colors = {
        "failure_pattern": "red",
        "success_pattern": "green",
        "anti_pattern": "yellow",
        "retry_strategy": "blue",
        "capability_gap": "magenta",
    }
    color = kind_colors.get(kind, "white")

    body = Text()
    body.append("Recommendation: ", style="bold")
    body.append(learning.get("recommendation", "?"))
    body.append("\n\nEvidence:\n", style="dim")
    body.append(learning.get("body", "?")[:500])

    tags = learning.get("domain_tags", [])
    if tags:
        body.append("\n\nTags: ", style="dim")
        body.append(", ".join(tags))

    agents = learning.get("agent_names", [])
    if agents:
        body.append("\nAgents: ", style="dim")
        body.append(", ".join(agents))

    subtitle = f"conf: {confidence:.0%} | {count}x"
    if promoted:
        subtitle += " | [magenta]PLATFORM[/magenta]"

    return Panel(
        body,
        title=f"[{color}]{kind}[/{color}] — {title}",
        subtitle=subtitle,
        border_style=color,
        box=box.ROUNDED,
    )


def render_learning_list(learnings: list[dict]) -> Table:
    """Render a list of learnings as a Rich Table."""
    table = Table(
        box=box.SIMPLE_HEAVY,
        title="Learnings",
    )
    table.add_column("Kind", width=16)
    table.add_column("Title", min_width=30)
    table.add_column("Conf", width=6, justify="right")
    table.add_column("Count", width=6, justify="right")
    table.add_column("Tags", min_width=15)
    table.add_column("Status", width=10)

    for learning in learnings:
        kind = learning.get("kind", "?")
        conf = learning.get("confidence", 0)
        promoted = learning.get("platform_promoted", False)
        status = "[magenta]platform[/magenta]" if promoted else learning.get("status", "?")

        table.add_row(
            kind,
            learning.get("title", "?")[:50],
            f"{conf:.0%}",
            str(learning.get("occurrence_count", 1)),
            ", ".join(learning.get("domain_tags", [])[:3]),
            status,
        )

    return table


def render_knowledge_search_results(entries: list[dict]) -> Table:
    """Render unified knowledge search results."""
    table = Table(
        box=box.SIMPLE_HEAVY,
        title="Knowledge Search Results",
    )
    table.add_column("Kind", width=12)
    table.add_column("Title", min_width=30)
    table.add_column("Tags", min_width=15)
    table.add_column("Conf", width=6, justify="right")
    table.add_column("Dist", width=6, justify="right")

    for e in entries:
        conf = e.get("confidence")
        dist = e.get("distance")
        table.add_row(
            e.get("kind", "?"),
            e.get("title", "?")[:50],
            ", ".join(e.get("domain_tags", [])[:3]),
            f"{conf:.0%}" if conf is not None else "-",
            f"{dist:.3f}" if dist is not None else "-",
        )

    return table
