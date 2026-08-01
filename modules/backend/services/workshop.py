"""
Workshop Service.

Single-agent testing sandbox. Runs one agent in isolation with optional
prompt override and cached inputs from previous workflow runs. Results
are persisted as workshop-tagged execution records for audit.

Workshop bypasses the full dispatch/planning/verification pipeline —
it's a direct agent invocation for prompt iteration and debugging.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai import UserError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.mission_control.cost import compute_cost_usd
from modules.backend.agents.mission_control.helpers import (
    _build_agent_deps,
    _build_model,
    _get_model_name,
    _get_usage_limits,
    _import_agent_module,
)
from modules.backend.core.agent_registry import get_registry
from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.services.base import BaseService

logger = get_logger(__name__)

WORKSHOP_CATEGORY = "workshop"


class WorkshopService(BaseService):
    """Single-agent sandbox for prompt iteration and testing."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["WorkshopService", None]:
        """Create a WorkshopService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield WorkshopService(db)
            await db.commit()

    async def run_agent(
        self,
        agent_name: str,
        *,
        inputs: dict[str, Any] | None = None,
        prompt_override: str | None = None,
        session_id: str | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        """Run a single agent in workshop mode.

        Args:
            agent_name: Fully qualified agent name from the registry.
            inputs: Input data to pass as the user message payload.
            prompt_override: If set, replaces the agent's system prompt
                entirely. This is temporary — not persisted to PromptVersion.
            session_id: Optional session ID for tracking.
            budget_usd: Optional per-run budget override.

        Returns:
            Dict with output, cost, tokens, and the execution_record_id.
        """
        config = get_app_config().workflows.workshop
        effective_budget = min(
            budget_usd or config.default_budget_usd,
            config.max_budget_usd,
        )

        registry = get_registry()
        agent_config = registry.get(agent_name)
        if agent_config is None:
            from modules.backend.core.exceptions import NotFoundError

            raise NotFoundError(f"Agent '{agent_name}' not found in registry")

        module = _import_agent_module(agent_name)
        model = _build_model(agent_config.model)

        agent = module.create_agent(model)
        if prompt_override:
            agent._system_prompts = (prompt_override,)

        deps = _build_agent_deps(agent_name, agent_config, session_id=session_id)
        usage_limits = _get_usage_limits(agent_name)

        user_message = "Execute with the provided inputs."
        if inputs:
            user_message = (
                f"Execute with the following inputs:\n\n"
                f"```json\n{json.dumps(inputs, indent=2, default=str)}\n```"
            )

        started_at = utc_now()

        try:
            async with agent.run_stream(
                user_message,
                deps=deps,
                usage_limits=usage_limits,
            ) as stream:
                try:
                    async for _ in stream.stream_text(delta=True):
                        pass
                except UserError:
                    logger.debug(
                        "Structured output agent — no text stream", extra={"agent_name": agent_name}
                    )

                output = await stream.get_output()
                usage = stream.usage()
        except Exception as e:
            # non-critical for mission-event visibility — this service has
            # no event_bus and re-raises immediately below, so the caller
            # sees the failure directly.
            logger.error(
                "Workshop agent execution failed",
                extra={"agent_name": agent_name, "error": str(e)},
            )
            raise

        completed_at = utc_now()

        if hasattr(output, "model_dump"):
            output_dict = output.model_dump()
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"result": str(output)}

        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        model_name = _get_model_name(agent_config.model)
        cost_usd = compute_cost_usd(input_tokens, output_tokens, model_name)

        if cost_usd > effective_budget:
            logger.warning(
                "Workshop run exceeded budget",
                extra={
                    "agent_name": agent_name,
                    "cost_usd": cost_usd,
                    "budget_usd": effective_budget,
                },
            )

        execution_record = await self._persist_workshop_run(
            agent_name=agent_name,
            session_id=session_id,
            output_dict=output_dict,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            started_at=started_at,
            completed_at=completed_at,
            inputs=inputs,
            had_prompt_override=prompt_override is not None,
        )

        self._log_operation(
            "Workshop run completed",
            agent_name=agent_name,
            cost_usd=cost_usd,
            execution_record_id=execution_record.id,
        )

        return {
            "execution_record_id": execution_record.id,
            "output": output_dict,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "model": model_name,
            "agent_name": agent_name,
            "had_prompt_override": prompt_override is not None,
        }

    async def get_cached_inputs(
        self,
        agent_name: str,
        mission_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve cached inputs from previous successful runs of this agent.

        Queries TaskExecution records where the agent matches and the status
        is completed, returning the output_data that could serve as inputs
        for re-testing.

        Args:
            agent_name: Agent to find cached inputs for.
            mission_id: Optional mission scope.
            limit: Max results (defaults to config).

        Returns:
            List of dicts with run metadata and cached data.
        """
        config = get_app_config().workflows.workshop
        effective_limit = limit or config.max_cached_input_sets

        stmt = (
            select(TaskExecution)
            .where(
                TaskExecution.agent_name == agent_name,
                TaskExecution.status == TaskExecutionStatus.COMPLETED,
            )
            .order_by(TaskExecution.created_at.desc())
            .limit(effective_limit)
        )

        if mission_id:
            stmt = stmt.join(
                ExecutionRecord,
                TaskExecution.execution_record_id == ExecutionRecord.id,
            ).where(ExecutionRecord.mission_id == mission_id)

        result = await self._session.execute(stmt)
        tasks = result.scalars().all()

        cached = []
        for task in tasks:
            cached.append(
                {
                    "task_execution_id": task.id,
                    "task_id": task.task_id,
                    "agent_name": task.agent_name,
                    "output_data": task.output_data,
                    "cost_usd": task.cost_usd,
                    "created_at": task.created_at,
                }
            )

        return cached

    async def list_runs(
        self,
        agent_name: str | None = None,
        limit: int = 20,
    ) -> list[ExecutionRecord]:
        """List workshop execution records.

        Args:
            agent_name: Optional filter by agent (matched via roster_name).
            limit: Max results.

        Returns:
            List of ExecutionRecord instances tagged as workshop runs.
        """
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.objective_category == WORKSHOP_CATEGORY)
            .order_by(ExecutionRecord.created_at.desc())
            .limit(limit)
        )

        if agent_name:
            stmt = stmt.where(ExecutionRecord.roster_name == agent_name)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_runs_as_dicts(
        self,
        agent_name: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List workshop runs as formatted dicts for API responses."""
        runs = await self.list_runs(agent_name=agent_name, limit=limit)
        return [
            {
                "id": r.id,
                "agent_name": r.roster_name,
                "status": r.status,
                "cost_usd": r.total_cost_usd,
                "created_at": r.created_at,
            }
            for r in runs
        ]

    async def _persist_workshop_run(
        self,
        *,
        agent_name: str,
        session_id: str | None,
        output_dict: dict,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        started_at: Any,  # datetime — passed directly to ExecutionRecord.started_at (DateTime column)  # noqa: E501
        completed_at: Any,  # datetime
        inputs: dict | None,
        had_prompt_override: bool,
    ) -> ExecutionRecord:
        """Persist a workshop run as an ExecutionRecord (no TaskExecution — see comment below)."""
        record = ExecutionRecord(
            session_id=session_id,
            status=ExecutionRecordStatus.COMPLETED.value,
            roster_name=agent_name,
            objective_statement=f"Workshop run: {agent_name}",
            objective_category=WORKSHOP_CATEGORY,
            total_cost_usd=cost_usd,
            started_at=started_at,
            completed_at=completed_at,
            execution_outcome_json={
                "workshop": True,
                "had_prompt_override": had_prompt_override,
                "inputs_provided": inputs is not None,
            },
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)

        # Workshop runs do NOT write a TaskExecution. Plan 72 promoted tasks to a
        # first-class entity with an FK from task_executions.task_id → tasks.id;
        # workshop runs are not tied to a real task, so any synthetic task_id would
        # violate the FK. The ExecutionRecord is sufficient audit per the service
        # docstring ("bypasses the full dispatch/planning/verification pipeline").
        # Token usage + cost live on the ExecutionRecord row already.

        return record

    @staticmethod
    def _parse_agent_path(agent_name: str) -> tuple[str, str]:
        """Parse 'category.subcategory.agent' into (category, name).

        Example: 'mission.planning.agent' -> ('mission', 'planning')
        """
        parts = agent_name.split(".")
        if len(parts) >= 2:
            return parts[0], parts[1]
        return parts[0], parts[0]
