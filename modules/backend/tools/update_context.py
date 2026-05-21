"""
Tool: update_context

Apply a key-value update to the Mission Context Document (MCD).
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def update_context(
    mission_id: str,
    *,
    path: str,
    value: str,
    reason: str = "",
) -> str:
    """Apply a key-value update to the Mission Context Document (MCD).

    Writes a single field at the given dot-notation path. The MCD is the
    persistent structured context for the mission — distinct from the
    workflow run context dict.

    Args:
        mission_id: Mission whose MCD to update.
        path: Dot-notation field path, e.g. "findings.classification".
        value: String value to set at that path.
        reason: Human-readable reason for the update (audit trail).

    Returns:
        Confirmation string with the new MCD version.
    """
    from modules.backend.services.mission_context import MissionContextManager

    async with MissionContextManager.factory() as mgr:
        new_version, errors = await mgr.apply_updates(
            mission_id,
            updates=[{"op": "set", "path": path, "value": value, "reason": reason or f"workflow update: {path}"}],
            agent_id="workflow",
        )

    if errors:
        logger.warning("Context update errors", extra={"mission_id": mission_id, "errors": errors})
        return f"Context update completed with errors: {errors}"

    logger.info("Context updated", extra={"mission_id": mission_id, "path": path, "version": new_version})
    return f"Context updated at '{path}' (MCD v{new_version})"


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "update_context",
    "description": "Apply a key-value update to the Mission Context Document (MCD)",
    "category": "context",
    "deps": ["mission_id"],
}

_impl = update_context
