"""
Execution Service.

Orchestrates execution lifecycle: creates executions from workflow steps,
instantiates Mission Control with the appropriate roster, tracks
ExecutionOutcome results, and manages inter-execution data flow.

Dispatch methods (run_execution, start_temporal_execution) live in
execution_dispatch.py and are mixed in via ExecutionDispatchMixin.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.agents.mission_control.models import EventBusProtocol, NoOpEventBus
from modules.backend.core.logging import get_logger
from modules.backend.core.protocols import ExecutionDispatchProtocol
from modules.backend.core.utils import utc_now
from modules.backend.models.execution import (
    Execution,
    ExecutionState,
    VALID_EXECUTION_TRANSITIONS,
)
from modules.backend.repositories.execution import ExecutionRepository
from modules.backend.services.base import BaseService
from modules.backend.services.execution_dispatch import ExecutionDispatchMixin

logger = get_logger(__name__)


class ExecutionService(ExecutionDispatchMixin, BaseService):
    """Execution lifecycle management."""

    def __init__(
        self,
        session: AsyncSession,
        mission_control_dispatch: ExecutionDispatchProtocol | None = None,
        session_service: Any | None = None,
        event_bus: EventBusProtocol = NoOpEventBus(),
    ) -> None:
        super().__init__(session)
        self._execution_repo = ExecutionRepository(session)
        self._mission_control_dispatch = mission_control_dispatch
        self._session_service = session_service
        self._event_bus = event_bus

    @staticmethod
    @asynccontextmanager
    async def factory(
        event_bus: "EventBusProtocol | None" = None,
    ) -> AsyncGenerator["ExecutionService", None]:
        """Create an ExecutionService with its own DB session.

        Each call gets an independent session, adapter, and service —
        safe for concurrent use in parallel workflow waves.

        Args:
            event_bus: Optional event bus for real-time progress events.
                       Defaults to NoOpEventBus if not provided.

        Usage:
            async with ExecutionService.factory() as svc:
                await svc.create_execution_from_step(...)
                await svc.run_execution(execution_id)
        """
        from modules.backend.agents.mission_control.dispatch_adapter import (
            MissionControlDispatchAdapter,
        )
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session import SessionService

        bus = event_bus or NoOpEventBus()

        async with get_async_session() as db:
            session_service = SessionService(db)
            adapter = MissionControlDispatchAdapter(
                session_service=session_service,
                db_session=db,
                event_bus=bus,
            )
            yield ExecutionService(
                session=db,
                mission_control_dispatch=adapter,
                session_service=session_service,
                event_bus=bus,
            )
            await db.commit()

    async def _publish_event(self, event: Any) -> None:
        """Publish event to session event bus (best-effort)."""
        try:
            await self._event_bus.publish(event)
        except (OSError, RuntimeError):
            logger.warning(
                "Failed to publish execution event",
                extra={"event_type": getattr(event, "event_type", "unknown"), "mission_id": getattr(event, "mission_id", None)},
            )

    # ---- Execution creation ----

    async def create_execution_from_step(
        self,
        workflow_run_id: str,
        step_id: str,
        objective: str,
        roster_ref: str,
        complexity_tier: str,
        cost_ceiling_usd: float,
        upstream_context: dict,
        session_id: str,
        environment: str = "local",
        mission_id: str | None = None,
    ) -> Execution:
        """Create an execution from a workflow step."""

        async def _create() -> Execution:
            app_config = get_app_config()
            active_count = await self._execution_repo.count_active()
            if active_count >= app_config.workflows.max_concurrent_missions:
                raise ValidationError(
                    message=(
                        f"Maximum concurrent executions "
                        f"({app_config.workflows.max_concurrent_missions}) "
                        f"reached. {active_count} currently active."
                    ),
                )

            execution = Execution(
                workflow_run_id=workflow_run_id,
                workflow_step_id=step_id,
                objective=objective,
                roster_ref=roster_ref,
                complexity_tier=complexity_tier,
                status=ExecutionState.PENDING,
                session_id=session_id,
                trigger_type="workflow",
                triggered_by=f"workflow_run:{workflow_run_id}",
                upstream_context=upstream_context,
                context={},
                total_cost_usd=0.0,
                cost_ceiling_usd=cost_ceiling_usd,
                mission_id=mission_id,
                execution_environment=environment,
            )
            self._session.add(execution)
            await self._session.flush()
            await self._session.refresh(execution)

            logger.info(
                "Execution created from workflow step",
                extra={
                    "execution_id": execution.id,
                    "workflow_run_id": workflow_run_id,
                    "step_id": step_id,
                    "roster_ref": roster_ref,
                    "complexity_tier": complexity_tier,
                    "cost_ceiling_usd": cost_ceiling_usd,
                },
            )
            return execution

        return await self._execute_db_operation(
            "create_execution_from_step", _create(),
        )

    async def create_adhoc_execution(
        self,
        objective: str,
        triggered_by: str,
        session_id: str | None = None,
        roster_ref: str = "default",
        complexity_tier: str = "simple",
        cost_ceiling_usd: float | None = None,
        upstream_context: dict | None = None,
        mission_id: str | None = None,
    ) -> Execution:
        """Create an ad-hoc execution (not from a workflow)."""
        if not session_id:
            from uuid import uuid4
            session_id = str(uuid4())

        async def _create() -> Execution:
            app_config = get_app_config()

            active_count = await self._execution_repo.count_active()
            if active_count >= app_config.workflows.max_concurrent_missions:
                raise ValidationError(
                    message=(
                        f"Maximum concurrent executions "
                        f"({app_config.workflows.max_concurrent_missions}) "
                        f"reached. {active_count} currently active."
                    ),
                )

            execution = Execution(
                objective=objective,
                roster_ref=roster_ref,
                complexity_tier=complexity_tier,
                status=ExecutionState.PENDING,
                session_id=session_id,
                trigger_type="on_demand",
                triggered_by=triggered_by,
                upstream_context=upstream_context or {},
                context={},
                total_cost_usd=0.0,
                mission_id=mission_id,
                cost_ceiling_usd=(
                    cost_ceiling_usd
                    or app_config.workflows.default_budget_usd
                ),
            )
            self._session.add(execution)
            await self._session.flush()
            await self._session.refresh(execution)

            logger.info(
                "Ad-hoc execution created",
                extra={
                    "execution_id": execution.id,
                    "session_id": session_id,
                    "roster_ref": roster_ref,
                },
            )
            return execution

        return await self._execute_db_operation(
            "create_adhoc_execution", _create(),
        )

    # ---- Execution lifecycle ----

    async def complete_execution(self, execution_id: str) -> Execution:
        """Mark execution as completed."""
        execution = await self._get_execution(execution_id)
        self._validate_transition(execution, ExecutionState.COMPLETED)

        execution.status = ExecutionState.COMPLETED
        execution.completed_at = utc_now()
        await self._session.flush()
        return execution

    async def fail_execution(
        self, execution_id: str, error: str,
        error_data: dict | None = None,
    ) -> Execution:
        """Mark execution as failed."""
        execution = await self._get_execution(execution_id)
        self._validate_transition(execution, ExecutionState.FAILED)

        execution.status = ExecutionState.FAILED
        execution.completed_at = utc_now()
        execution.error_data = error_data or {"message": error}
        await self._session.flush()
        return execution

    async def cancel_execution(self, execution_id: str, reason: str) -> Execution:
        """Cancel an execution."""
        execution = await self._get_execution(execution_id)
        self._validate_transition(execution, ExecutionState.CANCELLED)

        execution.status = ExecutionState.CANCELLED
        execution.completed_at = utc_now()
        execution.error_data = {"cancelled_reason": reason}
        await self._session.flush()
        return execution

    # ---- Output extraction (anti-corruption layer) ----

    def extract_outputs(
        self, execution: Execution, output_mapping: dict | None,
    ) -> dict[str, Any]:
        """Extract outputs from a completed execution's ExecutionOutcome
        according to the workflow step's output_mapping.

        task_results in the outcome is a list of TaskResult dicts.
        We index them by task_id for direct lookup, but also support
        matching source_task against agent_name (since the Planning
        Agent assigns dynamic task IDs like 'task-001' that won't
        match workflow-defined source_task names).
        """
        if not output_mapping:
            self._log_debug(
                "No output_mapping configured",
                execution_id=execution.id,
            )
            return {}
        if not execution.execution_outcome:
            logger.warning(
                "Execution has no outcome for output extraction",
                extra={"execution_id": execution.id, "mission_id": execution.mission_id},
            )
            return {}

        extracted: dict[str, Any] = {}
        outcome = execution.execution_outcome

        summary_key = output_mapping.get("summary_key")
        if summary_key:
            extracted[summary_key] = (
                outcome.get("summary") or execution.result_summary
            )

        field_mappings = output_mapping.get("field_mappings", [])
        raw_results = outcome.get("task_results", [])

        by_task_id: dict[str, dict] = {}
        by_agent: dict[str, list[dict]] = {}
        if isinstance(raw_results, list):
            for tr in raw_results:
                if isinstance(tr, dict):
                    by_task_id[tr.get("task_id", "")] = tr.get(
                        "output_reference", {},
                    )
                    agent = tr.get("agent_name", "")
                    by_agent.setdefault(agent, []).append(
                        tr.get("output_reference", {}),
                    )
        elif isinstance(raw_results, dict):
            by_task_id = raw_results

        for mapping in field_mappings:
            source_task = mapping["source_task"]
            source_field = mapping["source_field"]
            target_key = mapping["target_key"]

            task_output = by_task_id.get(source_task)
            if task_output is None:
                agent_outputs = by_agent.get(source_task, [])
                for candidate in agent_outputs:
                    if isinstance(candidate, dict) and source_field in candidate:
                        task_output = candidate
                        break
                else:
                    task_output = agent_outputs[0] if agent_outputs else None

            if task_output is not None:
                if isinstance(task_output, dict) and source_field in task_output:
                    extracted[target_key] = task_output[source_field]
                else:
                    logger.warning(
                        "Output mapping source field not found",
                        extra={
                            "execution_id": execution.id,
                            "source_task": source_task,
                            "source_field": source_field,
                            "available_fields": (
                                list(task_output.keys())
                                if isinstance(task_output, dict) else None
                            ),
                            "mission_id": execution.mission_id,
                        },
                    )
            else:
                logger.warning(
                    "Output mapping source task not found",
                    extra={
                        "execution_id": execution.id,
                        "source_task": source_task,
                        "available_task_ids": list(by_task_id.keys()),
                        "available_agents": list(by_agent.keys()),
                        "mission_id": execution.mission_id,
                    },
                )

        return extracted

    # ---- Status and queries ----

    async def get_execution(self, execution_id: str) -> Execution:
        """Get an execution by ID."""
        return await self._get_execution(execution_id)

    async def get_execution_or_none(self, execution_id: str) -> Execution | None:
        """Get an execution by ID, returning None if not found."""
        return await self._execution_repo.get_by_id_or_none(execution_id)

    async def list_live_executions(
        self,
        mission_id: str | None = None,
        limit: int = 50,
    ) -> list[Execution]:
        """List live/in-flight executions, optionally filtered by mission."""
        if not mission_id:
            return []
        executions, _ = await self._execution_repo.list_executions(
            mission_id=mission_id, limit=limit,
        )
        return executions

    async def list_executions(
        self,
        status: str | None = None,
        workflow_run_id: str | None = None,
        mission_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Execution], int]:
        """List executions with optional filters."""
        execution_status = ExecutionState(status) if status else None
        return await self._execution_repo.list_executions(
            status=execution_status,
            workflow_run_id=workflow_run_id,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
        )

    # ---- Internal helpers ----

    async def _get_execution(self, execution_id: str) -> Execution:
        """Get execution or raise NotFoundError."""
        execution = await self._execution_repo.get_by_id_or_none(execution_id)
        if not execution:
            raise NotFoundError(
                message=f"Execution '{execution_id}' not found",
            )
        return execution

    def _validate_transition(
        self, execution: Execution, new_status: ExecutionState,
    ) -> None:
        """Validate execution status transition."""
        current = ExecutionState(execution.status)
        allowed = VALID_EXECUTION_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValidationError(
                message=(
                    f"Cannot transition execution from '{current.value}' "
                    f"to '{new_status.value}'. "
                    f"Allowed: {[s.value for s in allowed]}"
                ),
            )
