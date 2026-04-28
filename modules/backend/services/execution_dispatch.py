"""
Execution Dispatch Mixin — extracted from execution.py.

Contains the dispatch-related methods (run_execution, start_temporal_execution)
that handle dispatching an execution to Mission Control or Temporal. Separated
because dispatch orchestration is a distinct concern from execution CRUD,
lifecycle transitions, output extraction, and queries.

Mixed into ExecutionService — do not instantiate directly.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.exceptions import ApplicationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution import ExecutionState

if TYPE_CHECKING:
    from modules.backend.models.execution import Execution

logger = get_logger(__name__)


class ExecutionDispatchMixin:
    """Dispatch-related methods for ExecutionService.

    Mixed into ExecutionService — do not instantiate directly.
    All methods reference self._session, self._mission_control_dispatch,
    self._event_bus, self._get_execution, and self._validate_transition
    which are set by ExecutionService.__init__() and inherited from
    BaseService.
    """

    async def run_execution(self, execution_id: str, gate: object | None = None) -> Execution:
        """Execute by dispatching to Mission Control."""
        execution = await self._get_execution(execution_id)
        self._validate_transition(execution, ExecutionState.RUNNING)

        execution.status = ExecutionState.RUNNING
        execution.started_at = utc_now()
        await self._session.flush()

        # Emit system event: execution started
        if execution.mission_id:
            from modules.backend.events.types import SystemExecutionCreatedEvent
            await self._event_bus.publish_to_mission(
                execution.mission_id,
                SystemExecutionCreatedEvent(
                    session_id=uuid.UUID(execution.session_id) if execution.session_id else uuid.uuid4(),
                    source="execution_service",
                    execution_id=execution_id,
                    mission_id=execution.mission_id,
                    objective=execution.objective or "",
                    triggered_by=execution.triggered_by or "unknown",
                ),
            )

        if self._mission_control_dispatch is None:
            logger.warning(
                "Mission Control dispatch not available, "
                "execution stays in RUNNING",
                extra={"execution_id": execution_id, "mission_id": execution.mission_id},
            )
            return execution

        try:
            # Extract container config from execution.context (set by
            # create_execution_from_step when a workflow step declares
            # container_image or extra_volumes).
            exec_ctx = execution.context or {}
            outcome = await self._mission_control_dispatch.execute(
                mission_brief=execution.objective,
                roster_ref=execution.roster_ref,
                complexity_tier=execution.complexity_tier,
                upstream_context=execution.upstream_context,
                cost_ceiling_usd=execution.cost_ceiling_usd,
                session_id=execution.session_id,
                mission_id=execution.mission_id,
                gate=gate,
                container_image=exec_ctx.get("container_image"),
                extra_volumes=exec_ctx.get("extra_volumes"),
            )

            execution.execution_outcome = (
                outcome if isinstance(outcome, dict)
                else outcome.model_dump()
            )
            execution.total_cost_usd = (
                outcome.get("total_cost_usd", 0.0)
                if isinstance(outcome, dict)
                else getattr(outcome, "total_cost_usd", 0.0)
            )
            execution.result_summary = (
                outcome.get("summary", None)
                if isinstance(outcome, dict)
                else getattr(outcome, "summary", None)
            )

            if (
                execution.cost_ceiling_usd
                and execution.total_cost_usd > execution.cost_ceiling_usd
            ):
                logger.warning(
                    "Execution exceeded cost ceiling",
                    extra={
                        "execution_id": execution_id,
                        "cost": execution.total_cost_usd,
                        "ceiling": execution.cost_ceiling_usd,
                        "mission_id": execution.mission_id,
                    },
                )

            success = (
                outcome.get("success", False)
                if isinstance(outcome, dict)
                else getattr(outcome, "success", False)
            )
            if success:
                execution.status = ExecutionState.COMPLETED
            else:
                execution.status = ExecutionState.FAILED
                execution.error_data = {
                    "message": "Mission Control dispatch returned failure",
                }

            execution.completed_at = utc_now()
            await self._session.flush()

            # Emit system event: execution completed
            if execution.mission_id:
                from modules.backend.events.types import SystemExecutionCompletedEvent
                duration = 0.0
                if execution.started_at and execution.completed_at:
                    try:
                        from datetime import datetime
                        t0 = datetime.fromisoformat(execution.started_at)
                        t1 = datetime.fromisoformat(execution.completed_at)
                        duration = (t1 - t0).total_seconds()
                    except (ValueError, TypeError):
                        pass
                await self._event_bus.publish_to_mission(
                    execution.mission_id,
                    SystemExecutionCompletedEvent(
                        session_id=uuid.UUID(execution.session_id) if execution.session_id else uuid.uuid4(),
                        source="execution_service",
                        execution_id=execution_id,
                        mission_id=execution.mission_id,
                        status=execution.status.value if hasattr(execution.status, 'value') else str(execution.status),
                        total_cost_usd=execution.total_cost_usd or 0.0,
                        duration_seconds=duration,
                    ),
                )

        except (ApplicationError, OSError, RuntimeError, ValueError) as e:
            execution.status = ExecutionState.FAILED
            execution.completed_at = utc_now()
            execution.error_data = {
                "message": str(e), "type": type(e).__name__,
            }
            await self._session.flush()
            logger.error(
                "Execution failed",
                extra={"execution_id": execution_id, "error": str(e), "mission_id": execution.mission_id},
            )
            # Emit system event: execution failed
            if execution.mission_id:
                from modules.backend.events.types import SystemExecutionCompletedEvent
                await self._event_bus.publish_to_mission(
                    execution.mission_id,
                    SystemExecutionCompletedEvent(
                        session_id=uuid.UUID(execution.session_id) if execution.session_id else uuid.uuid4(),
                        source="execution_service",
                        execution_id=execution_id,
                        mission_id=execution.mission_id,
                        status="failed",
                        total_cost_usd=execution.total_cost_usd or 0.0,
                    ),
                )
        except Exception as e:
            # Catch-all: ensure execution never gets stuck in RUNNING
            execution.status = ExecutionState.FAILED
            execution.completed_at = utc_now()
            execution.error_data = {
                "message": str(e), "type": type(e).__name__,
            }
            await self._session.flush()
            logger.exception(
                "Execution failed with unexpected error",
                extra={"execution_id": execution_id, "mission_id": execution.mission_id},
            )
            # Emit system event so the error surfaces in the console
            if execution.mission_id:
                from modules.backend.events.types import SystemExecutionCompletedEvent
                try:
                    await self._event_bus.publish_to_mission(
                        execution.mission_id,
                        SystemExecutionCompletedEvent(
                            session_id=uuid.UUID(execution.session_id) if execution.session_id else uuid.uuid4(),
                            source="execution_service",
                            execution_id=execution_id,
                            mission_id=execution.mission_id,
                            status="failed",
                            total_cost_usd=execution.total_cost_usd or 0.0,
                        ),
                    )
                except Exception:
                    pass  # best-effort — don't mask the original error

        return execution

    async def start_temporal_execution(self, execution_id: str) -> dict[str, str]:
        """Start an execution via Temporal workflow.

        Reads execution data from the persistence layer and submits
        a Temporal workflow. Returns workflow metadata dict.
        """
        from modules.backend.core.config import get_app_config
        from modules.backend.services.execution_persistence import ExecutionPersistenceService
        from modules.backend.temporal.client import get_temporal_client
        from modules.backend.temporal.models import MissionWorkflowInput
        from modules.backend.temporal.workflow import AgentMissionWorkflow

        config = get_app_config()
        persistence = ExecutionPersistenceService(self._session)
        record = await persistence.get_execution(execution_id)

        brief = ""
        roster = "default"
        budget = get_default_budget_usd()
        mission_id = None
        if record:
            brief = record.objective_statement or ""
            roster = record.roster_name or "default"
            # TODO: BUG — record.total_cost_usd is *already-spent* cost, not
            # the budget ceiling. Using it as the new ceiling means retries
            # inherit the previous run's spend as their cap. For now we fall
            # back to the configured default; the correct fix is to read the
            # budget ceiling from the mission plan or execution record.
            budget = get_default_budget_usd()
            mission_id = record.mission_id

        client = await get_temporal_client()
        handle = await client.start_workflow(
            AgentMissionWorkflow.run,
            MissionWorkflowInput(
                mission_run_id=execution_id,
                session_id=execution_id,
                mission_brief=brief,
                roster_name=roster,
                mission_budget_usd=budget,
                mission_id=mission_id,
                approval_timeout_seconds=config.temporal.approval_timeout_seconds,
                escalation_timeout_seconds=config.temporal.escalation_timeout_seconds,
                notification_timeout_seconds=config.temporal.notification_timeout_seconds,
            ),
            id=f"execution-{execution_id}",
            task_queue=config.temporal.task_queue,
        )

        return {
            "workflow_id": handle.id,
            "execution_id": execution_id,
            "status": "started",
        }
