"""
Context Curator.

Validates and applies context_updates from agent task results to the PCD.
Enforces size caps, restricted paths, and guardrail protection.
Delegates actual MCD mutation to MissionContextManager.
"""

from modules.backend.core.logging import get_logger
from modules.backend.services.mission_context import MissionContextManager

logger = get_logger(__name__)


class ContextCurator:
    """Validates and applies agent context_updates to the PCD.

    Thin orchestration layer between the dispatch loop and
    MissionContextManager. Keeps dispatch free of MCD internals.
    """

    def __init__(self, context_manager: MissionContextManager) -> None:
        self._manager = context_manager

    async def get_mission_context(self, mission_id: str) -> dict:
        """Load the current MCD for a mission.

        Returns {} if no MCD exists. Used by dispatch to inject
        mission_context into agent inputs.
        """
        return await self._manager.get_context(mission_id)

    async def apply_task_updates(
        self,
        mission_id: str,
        task_result_context_updates: list[dict],
        *,
        agent_id: str | None = None,
        mission_id_ref: str | None = None,
        task_id: str | None = None,
    ) -> tuple[int, list[str]]:
        """Apply context_updates from a task result to the PCD.

        Returns (new_version, list_of_errors).
        Errors are non-fatal — they are logged but do not fail the task.
        """
        if not task_result_context_updates:
            return 0, []

        new_version, errors = await self._manager.apply_updates(
            mission_id,
            task_result_context_updates,
            agent_id=agent_id,
            mission_id_ref=mission_id_ref,
            task_id=task_id,
        )

        if errors:
            logger.warning(
                "Context update errors (non-fatal)",
                extra={
                    "mission_id": mission_id,
                    "task_id": task_id,
                    "errors": errors,
                },
            )

        return new_version, errors
