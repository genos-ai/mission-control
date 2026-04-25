"""
Tool: query_knowledge

Query the knowledge platform for relevant entries.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def query_knowledge(
    mission_id: str,
    *,
    query: str = "",
    kinds: list[str] | None = None,
    domain_tags: list[str] | None = None,
    platform_only: bool = False,
    mode: str = "hybrid",
    limit: int = 10,
) -> str:
    """Query the knowledge platform for relevant entries.

    Returns a formatted text summary of matching entries.
    Agents call this to check prior learnings, decisions, and
    milestones before spending tokens discovering the same thing.

    Args:
        mission_id: Scope to this mission's knowledge (+ platform).
        query: Free-text search query.
        kinds: Filter by entry kind (learning, decision, milestone).
        domain_tags: Filter by domain tags.
        platform_only: Only platform-promoted entries.
        mode: Search mode (structured | hybrid | semantic).
        limit: Max results to return.
    """
    import json

    from modules.backend.services.knowledge import KnowledgeService

    async with KnowledgeService.factory() as svc:
        entries = await svc.search(
            query,
            mission_id=mission_id,
            platform_only=platform_only,
            kinds=kinds,
            domain_tags=domain_tags,
            mode=mode,
            limit=limit,
        )

    if not entries:
        return "No matching knowledge entries found."

    results = []
    for e in entries:
        entry_str = f"[{e.kind}] {e.title}"
        if e.confidence is not None:
            entry_str += f" (confidence: {e.confidence:.2f})"
        if e.distance is not None:
            entry_str += f" (distance: {e.distance:.3f})"
        entry_str += f"\n  {e.body[:300]}"
        if e.domain_tags:
            entry_str += f"\n  Tags: {', '.join(e.domain_tags)}"
        results.append(entry_str)

    return f"Found {len(entries)} knowledge entries:\n\n" + "\n\n".join(results)
