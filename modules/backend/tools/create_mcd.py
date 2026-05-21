"""
Tool: create_mcd

Create a Mission Context Document (MCD) for the mission if one does not exist.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def create_mcd(mission_id: str) -> str:
    """Create a seed MCD for the mission.

    Fetches the mission name and description from the database so the MCD
    is properly seeded.  Safe to call only when check_mcd returned "missing".

    Returns:
        Confirmation string with MCD version.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.repositories.mission import MissionRepository
    from modules.backend.services.mission_context import MissionContextManager

    async with get_async_session() as db:
        repo = MissionRepository(db)
        mission = await repo.get_by_id(mission_id)
        name = mission.name
        description = mission.description or ""

    async with MissionContextManager.factory() as mgr:
        ctx = await mgr.create_context(mission_id, name, description)

    logger.info("MCD created", extra={"mission_id": mission_id, "version": ctx.version})
    return f"MCD created (v{ctx.version}) for mission '{name}'"


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "create_mcd",
    "description": "Create a seed Mission Context Document (MCD) for the mission",
    "category": "context",
    "deps": ["mission_id"],
}

_impl = create_mcd
