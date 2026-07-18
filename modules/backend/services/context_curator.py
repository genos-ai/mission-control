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

        # Validate domain_tags in any update that writes to a tags path (Plan 57 §4.2)
        mcd = await self._manager.get_context(mission_id)
        task_result_context_updates = self._validate_domain_tags_in_updates(
            task_result_context_updates,
            mcd,
        )

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

    @staticmethod
    def _validate_domain_tags_in_updates(
        updates: list[dict],
        mcd: dict,
    ) -> list[dict]:
        """Validate and normalize domain_tags in context updates.

        Invalid tags are logged and dropped (per Plan 57 §4.2 —
        never block the parent write). Returns the cleaned updates list.
        """
        from modules.backend.core.domain_tags import validate_tags

        cleaned = []
        for update in updates:
            path = update.get("path", "")
            value = update.get("value")

            # Check if this update writes domain_tags
            if "domain_tags" in path and isinstance(value, list):
                valid, invalid = validate_tags(value, mcd)
                if invalid:
                    logger.debug(
                        "Domain tags dropped from context update",
                        extra={"path": path, "invalid": invalid, "valid": valid},
                    )
                update = {**update, "value": valid}

            cleaned.append(update)

        return cleaned
