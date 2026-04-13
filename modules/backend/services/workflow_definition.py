"""
Workflow Definition Service.

Business logic for DB-stored workflow definitions. Handles CRUD,
template import from YAML, and validation against WorkflowSchema.

The existing WorkflowService (workflow.py) remains for YAML template
loading. This service is the DB-backed counterpart for mission-scoped
workflows.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository
from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class WorkflowDefinitionService(BaseService):
    """Service for DB-backed workflow definitions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = WorkflowDefinitionRepository(session)
        self._mission_repo = MissionRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["WorkflowDefinitionService", None]:
        """Create a WorkflowDefinitionService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield WorkflowDefinitionService(db)
            await db.commit()

    async def create_workflow(
        self,
        mission_id: str | None,
        name: str,
        description: str,
        objective: dict[str, Any],
        steps: list[dict[str, Any]],
        *,
        trigger_config: dict[str, Any] | None = None,
        budget_config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        designed_by: str | None = None,
    ) -> WorkflowDefinition:
        """Create a new workflow definition for a mission (or system template when None)."""
        if mission_id is not None:
            await self._mission_repo.get_by_id(mission_id)

        existing = await self._repo.get_by_mission_and_name(mission_id, name)
        if existing:
            raise ConflictError(
                f"Workflow '{name}' already exists for this mission"
            )

        self._validate_steps(steps)

        workflow = await self._repo.create(
            mission_id=mission_id,
            name=name,
            description=description,
            objective=objective,
            steps=steps,
            trigger_config=trigger_config or {"type": "on_demand"},
            budget_config=budget_config or {"max_cost_usd": 10.0},
            context=context or {},
            designed_by=designed_by,
        )

        self._log_operation(
            "Workflow definition created",
            mission_id=mission_id,
            workflow_name=name,
        )
        return workflow

    async def get_workflow(
        self,
        mission_id: str | None,
        name: str,
    ) -> WorkflowDefinition:
        """Get a workflow by mission + name. Raises NotFoundError.

        When mission_id is None, looks up system templates (mission_id IS NULL).
        """
        workflow = await self._repo.get_by_mission_and_name(mission_id, name)
        if not workflow:
            scope = f"mission '{mission_id}'" if mission_id else "system templates"
            raise NotFoundError(
                f"Workflow '{name}' not found in {scope}"
            )
        return workflow

    async def list_workflows(
        self,
        mission_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[WorkflowDefinition]:
        """List workflow definitions for a mission, or system templates when None."""
        if mission_id is None:
            return await self._repo.list_templates(enabled_only=enabled_only)
        return await self._repo.list_by_mission(mission_id, enabled_only=enabled_only)

    async def update_workflow(
        self,
        workflow_id: str,
        **updates: Any,
    ) -> WorkflowDefinition:
        """Update a workflow definition."""
        if "steps" in updates:
            self._validate_steps(updates["steps"])
        return await self._repo.update(workflow_id, **updates)

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow definition by ID."""
        await self._repo.delete(workflow_id)

    async def lock_workflow(self, workflow_id: str) -> WorkflowDefinition:
        """Lock a workflow (user confirmed the design)."""
        from modules.backend.core.utils import utc_now
        return await self._repo.update(
            workflow_id, locked_at=utc_now().isoformat(),
        )

    async def import_from_template(
        self,
        mission_id: str,
        template_name: str,
        *,
        name_override: str | None = None,
    ) -> WorkflowDefinition:
        """Import a YAML template as a mission workflow.

        Loads the template via WorkflowService (YAML), converts to DB
        format, and saves as a new workflow definition.
        """
        from modules.backend.services.workflow import WorkflowService

        template_service = WorkflowService()
        template = template_service.get_workflow(template_name)
        if not template:
            raise NotFoundError(
                f"Workflow template '{template_name}' not found"
            )

        workflow_name = name_override or template.workflow_name.replace(".workflow", "")

        return await self.create_workflow(
            mission_id=mission_id,
            name=workflow_name,
            description=template.description,
            objective=template.objective.model_dump(),
            steps=[s.model_dump() for s in template.steps],
            trigger_config=template.trigger.model_dump(),
            budget_config=template.budget.model_dump(),
            context=template.context,
            designed_by="import:yaml_template",
        )

    async def list_templates(self, enabled_only: bool = True) -> list[WorkflowDefinition]:
        """List system workflow templates (mission_id=NULL)."""
        return await self._repo.list_templates(enabled_only=enabled_only)

    def _validate_steps(self, steps: list[dict[str, Any]]) -> None:
        """Validate step structure using WorkflowSchema's step validator."""
        if not steps:
            raise ValidationError("Workflow must have at least one step")

        try:
            from modules.backend.schemas.workflow import WorkflowStepSchema
            for step_data in steps:
                WorkflowStepSchema(**step_data)
        except (TypeError, ValueError, KeyError) as e:
            raise ValidationError(f"Invalid step definition: {e}") from e
