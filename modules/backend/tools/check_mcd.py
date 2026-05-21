"""
Tool: check_mcd

Check whether a Mission Context Document (MCD) exists for the mission.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def check_mcd(mission_id: str) -> str:
    """Check whether an MCD exists for the mission.

    Returns:
        "exists" if an MCD is present, "missing" if not.
    """
    from modules.backend.services.mission_context import MissionContextManager

    async with MissionContextManager.factory() as mgr:
        data = await mgr.get_context(mission_id)

    # get_context returns {} when no MCD exists
    result = "exists" if data else "missing"
    logger.info("MCD check", extra={"mission_id": mission_id, "result": result})
    return result


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "check_mcd",
    "description": "Check whether a Mission Context Document (MCD) exists for the mission",
    "category": "context",
    "deps": ["mission_id"],
}

_impl = check_mcd
