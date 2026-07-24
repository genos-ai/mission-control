"""
mc intent / mc learnings / mc knowledge — knowledge platform handlers.

All operations go through the HTTP API. Zero backend service imports.
"""

from modules.clients.cli.api_client import CliApiClient, extract_list
from modules.clients.common.display import get_console
from modules.clients.common.knowledge_rendering import (
    render_intent,
    render_intent_history,
    render_knowledge_search_results,
    render_learning_card,
    render_learning_list,
)

# =============================================================================
# Intent
# =============================================================================


async def intent_show(api: CliApiClient, mission_id: str) -> None:
    """Show the current mission intent."""
    console = get_console()
    data = await api.get(f"/missions/{mission_id}/intent")
    if data:
        console.print(render_intent(data))
    else:
        console.print("[dim]No intent set for this mission.[/dim]")


async def intent_history(
    api: CliApiClient,
    mission_id: str,
    limit: int = 20,
) -> None:
    """Show intent revision timeline."""
    console = get_console()
    data = await api.get(
        f"/missions/{mission_id}/intent/history",
        params={"limit": limit},
    )
    items = extract_list(data, "items")
    if items:
        console.print(
            render_intent_history(
                [
                    {
                        "intent_summary": r.get("intent_summary", r.get("intent", "")),
                        "source": r.get("source", ""),
                        "reason": r.get("reason", ""),
                        "created_at": str(r.get("created_at", "")),
                    }
                    for r in items
                ]
            )
        )
    else:
        console.print("[dim]No intent revisions yet.[/dim]")


async def intent_set(
    api: CliApiClient,
    mission_id: str,
    intent_text: str,
    reason: str = "User-set via CLI",
) -> None:
    """Set a new mission intent."""
    console = get_console()
    result = await api.post(
        f"/missions/{mission_id}/intent",
        body={
            "intent": intent_text,
            "source": "user_cli",
            "reason": reason,
        },
    )
    if result and result.get("status") != "dedup":
        summary = result.get("intent_summary", result.get("intent", intent_text))
        console.print(f"[green]Intent updated:[/green] {summary}")
    else:
        console.print("[dim]Intent unchanged (identical to current).[/dim]")


# =============================================================================
# Learnings
# =============================================================================


def _normalize_learning(raw: dict) -> dict:
    """Transform raw API learning dict to render_learning_* shape."""
    return {
        "kind": raw.get("kind", ""),
        "title": raw.get("title", ""),
        "body": raw.get("body", ""),
        "recommendation": raw.get("recommendation", ""),
        "confidence": raw.get("confidence", 0),
        "occurrence_count": raw.get("occurrence_count", 0),
        "domain_tags": raw.get("domain_tags", []),
        "agent_names": raw.get("agent_names", []),
        "platform_promoted": raw.get("platform_promoted", False),
        "status": raw.get("status", ""),
        "created_at": str(raw.get("created_at", "")),
    }


async def learnings_list(
    api: CliApiClient,
    mission_id: str,
    kind: str | None = None,
    domain: str | None = None,
) -> None:
    """List learnings for the current mission."""
    console = get_console()
    params: dict = {}
    if kind:
        params["kind"] = kind
    if domain:
        params["domain_tags"] = domain

    data = await api.get(f"/missions/{mission_id}/learnings", params=params)
    items = extract_list(data, "items")

    if items:
        console.print(render_learning_list([_normalize_learning(item) for item in items]))
    else:
        console.print("[dim]No learnings extracted yet.[/dim]")


async def learnings_show(
    api: CliApiClient,
    mission_id: str,
    learning_id: str,
) -> None:
    """Show a specific learning in detail."""
    console = get_console()
    learning = await api.get(
        f"/missions/{mission_id}/learnings/{learning_id}",
    )
    console.print(render_learning_card(_normalize_learning(learning)))


# =============================================================================
# Knowledge search
# =============================================================================


async def knowledge_search(
    api: CliApiClient,
    query: str,
    mission_id: str | None = None,
    tags: str | None = None,
    kinds: str | None = None,
    mode: str = "hybrid",
    platform_only: bool = False,
) -> None:
    """Search the knowledge platform."""
    console = get_console()
    params: dict = {"q": query, "mode": mode}
    if mission_id:
        params["mission_id"] = mission_id
    if tags:
        params["tags"] = tags
    if kinds:
        params["kinds"] = kinds
    if platform_only:
        params["platform_only"] = "true"

    entries = await api.get("/knowledge/search", params=params)
    items = entries if isinstance(entries, list) else (entries or [])

    if items:
        console.print(
            render_knowledge_search_results(
                [
                    {
                        "kind": e.get("kind", ""),
                        "title": e.get("title", ""),
                        "domain_tags": e.get("domain_tags", []),
                        "confidence": e.get("confidence", 0),
                        "distance": e.get("distance", 0),
                    }
                    for e in items
                ]
            )
        )
    else:
        console.print("[dim]No matching knowledge entries found.[/dim]")
