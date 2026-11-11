"""
Execution Persistence Service.

Saves Mission Control execution artifacts to PostgreSQL for audit,
compliance, cost analytics, and historical queries.

Called by the dispatch loop (Plan 13) during and after execution.
This service is write-heavy during execution and read-heavy afterward.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.decision_reasoning import decode_decision_reasoning
from modules.backend.core.exceptions import WorkflowOutputMappingError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import (
    DecisionType,
    ExecutionDecision,
    ExecutionRecord,
    ExecutionRecordStatus,
    FailureTier,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.execution_record import ExecutionCostBreakdown
from modules.backend.schemas.task_failure import TaskFailure
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _to_datetime(value: str | datetime | None) -> datetime | None:
    """Coerce a string or datetime to a datetime. Returns None if empty."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


class ExecutionPersistenceService(BaseService):
    """Persist and query execution records.

    Write methods are called during/after dispatch loop execution.
    Read methods serve the REST API and analytics.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = ExecutionRecordRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> "AsyncGenerator[ExecutionPersistenceService, None]":
        """Create an ExecutionPersistenceService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield ExecutionPersistenceService(db)
            await db.commit()

    # ---- Write operations (called by dispatch loop) ----

    async def save_execution(
        self,
        session_id: str,
        status: str,
        *,
        roster_name: str | None = None,
        execution_outcome_json: dict | None = None,
        planning_thinking_trace: str | None = None,
        total_cost_usd: float = 0.0,
        started_at: str | None = None,
        completed_at: str | None = None,
        objective_statement: str | None = None,
        objective_category: str | None = None,
        mission_id: str | None = None,
        # Plan 71: workflow step tracking columns
        workflow_run_id: str | None = None,
        workflow_step_id: str | None = None,
        execution_environment: str | None = None,
        cost_ceiling_usd: float | None = None,
    ) -> ExecutionRecord:
        """Persist a complete execution record.

        Called after the dispatch loop completes (or fails/times out).
        """
        config = get_app_config().executions

        if planning_thinking_trace and config.persist_thinking_trace:
            if len(planning_thinking_trace) > config.max_thinking_trace_length:
                planning_thinking_trace = (
                    planning_thinking_trace[: config.max_thinking_trace_length] + "\n\n[TRUNCATED]"
                )
        elif not config.persist_thinking_trace:
            planning_thinking_trace = None

        # Infer sensible defaults for timestamps based on status:
        # - PENDING: neither started nor completed
        # - RUNNING: started but not completed
        # - Terminal: both started and completed
        is_terminal = status in ("completed", "failed", "cancelled", "timed_out")
        has_started = status != "pending"
        resolved_started = _to_datetime(started_at) or (utc_now() if has_started else None)
        resolved_completed = _to_datetime(completed_at) or (utc_now() if is_terminal else None)

        record = ExecutionRecord(
            session_id=session_id,
            roster_name=roster_name,
            status=ExecutionRecordStatus(status),
            execution_outcome_json=execution_outcome_json,
            planning_thinking_trace=planning_thinking_trace,
            total_cost_usd=total_cost_usd,
            started_at=resolved_started,
            completed_at=resolved_completed,
            objective_statement=objective_statement,
            objective_category=objective_category,
            mission_id=mission_id,
            workflow_run_id=workflow_run_id,
            workflow_step_id=workflow_step_id,
            execution_environment=execution_environment,
            cost_ceiling_usd=cost_ceiling_usd,
        )

        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)

        logger.info(
            "Execution record saved",
            extra={
                "execution_id": record.id,
                "session_id": session_id,
                "roster": roster_name,
                "status": status,
                "cost": total_cost_usd,
            },
        )

        return record

    async def complete_execution(
        self,
        execution_record_id: str,
        status: str,
        *,
        roster_name: str | None = None,
        execution_outcome_json: dict | None = None,
        planning_thinking_trace: str | None = None,
        total_cost_usd: float | None = None,
    ) -> ExecutionRecord:
        """Update an existing execution record with final results.

        Called by persist_mission_results when an early record was
        created at dispatch start. Transitions the record from
        'running' to the final status and fills in outcome data.

        Fields that are None are preserved (not overwritten).
        """
        config = get_app_config().executions

        if planning_thinking_trace and config.persist_thinking_trace:
            if len(planning_thinking_trace) > config.max_thinking_trace_length:
                planning_thinking_trace = (
                    planning_thinking_trace[: config.max_thinking_trace_length] + "\n\n[TRUNCATED]"
                )
        elif not config.persist_thinking_trace:
            planning_thinking_trace = None

        record = await self._repo.get_by_id(execution_record_id)
        record.status = ExecutionRecordStatus(status)
        record.completed_at = utc_now()
        if total_cost_usd is not None:
            record.total_cost_usd = total_cost_usd
        record.execution_outcome_json = execution_outcome_json
        record.planning_thinking_trace = planning_thinking_trace
        if roster_name:
            record.roster_name = roster_name
        # Plan 72: task_plan_json no longer stored on execution_records

        await self._session.flush()

        logger.info(
            "Execution record completed",
            extra={
                "execution_id": record.id,
                "status": status,
                "cost": total_cost_usd,
            },
        )
        return record

    async def record_run_task_counts(
        self, execution_record_id: str, mission_run_id: str
    ) -> ExecutionRecord:
        """Set the record's completed/failed task counts from the run's tasks.

        Recomputed from Task rows on every call, so a retried or repeated
        wave never double counts. The post-run stall rule reads these.
        """
        tasks = await TaskRepository(self._session).list_by_run(mission_run_id)
        record = await self._repo.get_by_id(execution_record_id)
        record.completed_task_count = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        record.failed_task_count = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        await self._session.flush()
        return record

    async def save_task_execution(
        self,
        execution_record_id: str,
        task_id: str,
        agent_name: str,
        status: str,
        *,
        output_data: dict | None = None,
        token_usage: dict | None = None,
        cost_usd: float = 0.0,
        duration_seconds: float | None = None,
        verification_outcome: dict | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        execution_id: str | None = None,
        domain_tags: list[str] | None = None,
        mission_run_id: str | None = None,
        idempotency_key: str | None = None,
        failure: TaskFailure | None = None,
    ) -> TaskExecution:
        """Persist a single task execution result.

        mission_run_id links the row to its run and idempotency_key
        (`{mission_run_id}:{task_id}:{retry_count}`, 3.1.9) makes a retried
        activity's write unique; both None outside a mission run. ``failure``
        is the attempt's classified failure (contracts 3.8.6), None unless it failed.
        """
        config = get_app_config().executions

        if output_data:
            output_size = len(json.dumps(output_data).encode("utf-8"))
            if output_size > config.max_task_output_size_bytes:
                output_data = {
                    "_truncated": True,
                    "_original_size_bytes": output_size,
                    "_message": "Output truncated. Exceeded max_task_output_size_bytes.",
                }

        if verification_outcome and not config.persist_verification_details:
            verification_outcome = {
                "passed": verification_outcome.get("passed"),
                "tier": verification_outcome.get("tier"),
            }

        # Validate domain tags (Plan 57 §4.2 — log and drop invalid, never block)
        if domain_tags:
            from modules.backend.core.domain_tags import validate_tags

            domain_tags, _ = validate_tags(domain_tags)

        execution = TaskExecution(
            execution_record_id=execution_record_id,
            task_id=task_id,
            agent_name=agent_name,
            status=TaskExecutionStatus(status),
            output_data=output_data,
            token_usage=token_usage,
            cost_usd=cost_usd,
            duration_seconds=duration_seconds,
            verification_outcome=verification_outcome,
            started_at=started_at,
            completed_at=completed_at,
            execution_id=execution_id,
            domain_tags=domain_tags,
            mission_run_id=mission_run_id,
            idempotency_key=idempotency_key,
        )
        self._repo.set_task_execution_failure(execution, failure)

        self._session.add(execution)
        await self._session.flush()
        await self._session.refresh(execution)

        logger.debug(
            "Task execution saved",
            extra={
                "execution_id": execution.id,
                "record_id": execution_record_id,
                "task_id": task_id,
                "agent": agent_name,
                "status": status,
                "cost": cost_usd,
            },
        )

        return execution

    async def save_attempt(
        self,
        task_execution_id: str,
        attempt_number: int,
        status: str,
        *,
        failure_tier: str | None = None,
        failure_reason: str | None = None,
        feedback_provided: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> TaskAttempt:
        """Persist a single task attempt within a task execution."""
        attempt = TaskAttempt(
            task_execution_id=task_execution_id,
            attempt_number=attempt_number,
            status=TaskAttemptStatus(status),
            failure_tier=FailureTier(failure_tier) if failure_tier else None,
            failure_reason=failure_reason,
            feedback_provided=feedback_provided,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

        self._session.add(attempt)
        await self._session.flush()
        await self._session.refresh(attempt)

        return attempt

    @staticmethod
    def _build_decision_row(
        execution_record_id: str,
        decision_type: str,
        reasoning: str,
        *,
        task_id: str | None = None,
    ) -> ExecutionDecision:
        return ExecutionDecision(
            execution_record_id=execution_record_id,
            decision_type=DecisionType(decision_type),
            task_id=task_id,
            reasoning=reasoning,
        )

    async def save_decision(
        self,
        execution_record_id: str,
        decision_type: str,
        reasoning: str,
        *,
        task_id: str | None = None,
    ) -> ExecutionDecision:
        """Log a Mission Control decision."""
        decision = self._build_decision_row(
            execution_record_id, decision_type, reasoning, task_id=task_id
        )

        self._session.add(decision)
        await self._session.flush()
        await self._session.refresh(decision)

        logger.debug(
            "Decision logged",
            extra={
                "decision_id": decision.id,
                "record_id": execution_record_id,
                "type": decision_type,
                "task_id": task_id,
            },
        )

        return decision

    # ---- Read operations (serve REST API) ----

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        """Get an execution record with all details loaded."""
        return await self._repo.get_with_details(execution_id)

    async def get_task_executions(self, execution_id: str) -> list:
        """Get task executions for an execution."""
        return await self._repo.get_task_executions(execution_id)

    async def list_executions(
        self,
        status: str | None = None,
        roster_name: str | None = None,
        objective_category: str | None = None,
        mission_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[ExecutionRecord], int]:
        """List execution records with optional filters."""
        config = get_app_config().executions
        if limit is None:
            limit = config.default_page_size
        limit = min(limit, config.max_page_size)

        try:
            record_status = ExecutionRecordStatus(status) if status else None
        except ValueError:
            record_status = None
        return await self._repo.list_executions(
            status=record_status,
            roster_name=roster_name,
            objective_category=objective_category,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
        )

    async def get_decisions(self, execution_id: str) -> list[ExecutionDecision]:
        """Get the decision audit trail for an execution."""
        return await self._repo.get_decisions(execution_id)

    def add_decision_row(
        self,
        execution_record_id: str,
        decision_type: str,
        reasoning: str,
        *,
        task_id: str | None = None,
    ) -> ExecutionDecision:
        """Stage a new ExecutionDecision row without flushing.

        Deliberately synchronous — session.add() is a memory operation;
        the caller owns the flush/commit. Used by gate reviewers that
        write the audit row as a side effect of building a GateDecision,
        inside a transaction they don't want to prematurely flush.
        """
        row = self._build_decision_row(
            execution_record_id, decision_type, reasoning, task_id=task_id
        )
        self._session.add(row)
        return row

    async def get_cached_decision_by_type(
        self,
        execution_record_id: str,
        decision_type: str,
        *,
        iteration: int,
    ) -> ExecutionDecision | None:
        """Return the first decision of a given type recorded for this iteration, if any.

        Used by idempotency checks (e.g. the post-run gate reviewer). One
        ExecutionRecord spans every iteration of a mission run, so a decision
        matches only when its decoded reasoning meta has iteration == iteration.
        """
        decisions = await self.get_decisions(execution_record_id)
        for decision in decisions:
            if decision.decision_type != DecisionType(decision_type):
                continue
            _, meta = decode_decision_reasoning(decision.reasoning or "")
            if meta.get("iteration") == iteration:
                return decision
        return None

    async def list_recent_run_outcomes(
        self,
        mission_id: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Read the last N execution records for a mission.

        Returns a list of dicts with run metadata, task counts, cost,
        and status. Used by the supervisor's chat mode to answer "what
        happened in the last few waves?" and by the decision matrix to
        feed GateContext.recent_run_outcomes.
        """
        from sqlalchemy import select

        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.mission_id == mission_id)
            .order_by(ExecutionRecord.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        return [
            {
                "execution_record_id": r.id,
                "status": r.status if isinstance(r.status, str) else r.status.value,
                "total_cost_usd": r.total_cost_usd,
                "completed_task_count": getattr(r, "completed_task_count", 0),
                "failed_task_count": getattr(r, "failed_task_count", 0),
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]

    async def list_past_decisions(
        self,
        mission_id: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Read post_run_supervisor decisions for a mission.

        Queries execution_decisions joined through execution_records to
        filter by mission_id. Returns the human-readable prefix and the
        structured JSON tail from the reasoning field.
        """
        from sqlalchemy import and_, select

        stmt = (
            select(ExecutionDecision)
            .join(
                ExecutionRecord,
                ExecutionDecision.execution_record_id == ExecutionRecord.id,
            )
            .where(
                and_(
                    ExecutionRecord.mission_id == mission_id,
                    ExecutionDecision.decision_type == DecisionType.POST_RUN_SUPERVISOR.value,
                )
            )
            .order_by(ExecutionDecision.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        decisions = []
        for row in rows:
            human_text, meta = decode_decision_reasoning(row.reasoning or "")

            decisions.append(
                {
                    "decision_id": row.id,
                    "execution_record_id": row.execution_record_id,
                    "action": meta.get("action", "unknown"),
                    "rule": meta.get("rule", "unknown"),
                    "reviewer": meta.get("reviewer", "unknown"),
                    "reason": human_text,
                    "model_metadata": meta.get("model_metadata"),
                    "created_at": str(row.created_at),
                }
            )

        return decisions

    async def get_cost_breakdown(self, execution_id: str) -> ExecutionCostBreakdown:
        """Get detailed cost breakdown for an execution."""
        record = await self._repo.get_by_id_or_none(execution_id)
        if not record:
            from modules.backend.core.exceptions import NotFoundError

            raise NotFoundError(f"Execution '{execution_id}' not found")

        executions = await self._repo.get_task_executions(execution_id)
        model_costs = await self._repo.get_cost_by_model(execution_id)

        task_costs: list[dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_attempts = 0

        for execution in executions:
            input_tok = 0
            output_tok = 0
            if execution.token_usage:
                input_tok = execution.token_usage.get("input_tokens", 0)
                output_tok = execution.token_usage.get("output_tokens", 0)
            total_input_tokens += input_tok
            total_output_tokens += output_tok
            task_cost: dict[str, Any] = {
                "task_id": execution.task_id,
                "agent_name": execution.agent_name,
                "cost_usd": execution.cost_usd,
                "status": execution.status,
                "duration_seconds": execution.duration_seconds,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
            }

            total_attempts += len(execution.attempts)
            task_costs.append(task_cost)

        return ExecutionCostBreakdown(
            execution_id=execution_id,
            total_cost_usd=record.total_cost_usd,
            task_costs=task_costs,
            model_costs=model_costs,
            attempt_count=total_attempts,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
        )

    async def get_execution_status(self, execution_id: str) -> dict:
        """Get execution progress summary as a dict.

        Returns a dict with execution_id, status, objective, task counts,
        and progress percentage. Used by Temporal Queries and the
        /missions/{id}/status API endpoint.
        """
        record = await self._repo.get_by_id_or_none(execution_id)
        if not record:
            from modules.backend.core.exceptions import NotFoundError

            raise NotFoundError(f"Execution '{execution_id}' not found")

        executions = await self._repo.get_task_executions(execution_id)

        total = len(executions)
        completed = sum(1 for e in executions if e.status == TaskExecutionStatus.COMPLETED)
        failed = sum(1 for e in executions if e.status == TaskExecutionStatus.FAILED)
        skipped = sum(1 for e in executions if e.status == TaskExecutionStatus.SKIPPED)

        progress_pct = (completed / total * 100.0) if total > 0 else 0.0

        return {
            "execution_id": execution_id,
            "status": (
                record.status.value if hasattr(record.status, "value") else str(record.status)
            ),
            "objective": record.objective_statement,
            "roster_name": record.roster_name,
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "skipped_tasks": skipped,
            "progress_pct": round(progress_pct, 1),
            "total_cost_usd": record.total_cost_usd,
        }

    async def get_executions_by_session(
        self,
        session_id: str,
    ) -> list[ExecutionRecord]:
        """Get all execution records for a session."""
        return await self._repo.get_by_session(session_id)

    # ---- Background task operations (Plan 56 Phase B) ----

    async def create_background_record(
        self,
        *,
        mission_id: str,
        session_id: str | None,
        task_type: str,
        objective: str,
        params: dict,
    ) -> ExecutionRecord:
        """Create an ExecutionRecord for a background task forked from a Director tool."""
        return await self._repo.create(
            session_id=session_id,
            mission_id=mission_id,
            status=ExecutionRecordStatus.PENDING,
            task_type=task_type,
            task_params=params,
            objective_statement=objective,
            total_cost_usd=0.0,
        )

    async def list_background_tasks(
        self,
        mission_id: str,
        limit: int = 10,
    ) -> list[ExecutionRecord]:
        """List recent background tasks (execution records with task_type set)."""
        from sqlalchemy import select

        result = await self._session.execute(
            select(ExecutionRecord)
            .where(
                ExecutionRecord.mission_id == mission_id,
                ExecutionRecord.task_type.isnot(None),
            )
            .order_by(ExecutionRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all_runs(
        self,
        mission_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Unified run history from execution_records.

        execution_records is the single source of truth for all runs —
        plan dispatches, research, workflow steps, and background tasks.
        Every execution path creates an early ExecutionRecord so both
        in-flight and completed runs are visible.

        Returns (runs, total_count) where each run is a normalized dict.
        """
        records, total = await self.list_executions(
            mission_id=mission_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        runs: list[dict] = []
        for r in records:
            r_status = r.status.value if hasattr(r.status, "value") else str(r.status)
            runs.append(
                {
                    "id": str(r.id),
                    "objective": r.objective_statement,
                    "status": r_status,
                    "roster_name": r.roster_name,
                    "total_cost_usd": float(r.total_cost_usd or 0),
                    "started_at": str(r.started_at) if r.started_at else None,
                    "completed_at": str(r.completed_at) if r.completed_at else None,
                    "created_at": str(r.created_at) if r.created_at else None,
                    "task_type": r.task_type,
                    "task_count": len(r.task_executions or []),
                    "execution_record_id": str(r.id),
                }
            )

        return runs, total

    async def get_cross_mission_cost_breakdown(self) -> dict[str, Any]:
        """Aggregate cost and execution count grouped by mission.

        Used by the Platform Director's cost-analytics tool. Missions
        with no mission_id (unscoped runs) group under "unscoped".
        """
        from sqlalchemy import func, select

        result = await self._session.execute(
            select(
                ExecutionRecord.mission_id,
                func.sum(ExecutionRecord.total_cost_usd).label("total_cost"),
                func.count(ExecutionRecord.id).label("execution_count"),
            ).group_by(ExecutionRecord.mission_id)
        )
        rows = result.all()

        return {
            "mission_costs": [
                {
                    "mission_id": str(row.mission_id) if row.mission_id else "unscoped",
                    "total_cost_usd": float(row.total_cost or 0),
                    "execution_count": row.execution_count,
                }
                for row in rows
            ],
            "platform_total_usd": sum(float(r.total_cost or 0) for r in rows),
        }

    # ---- Concurrency limiter (Plan 71) ----

    async def count_active(self) -> int:
        """Count in-flight execution records (PENDING or RUNNING).

        Counts ALL run types (plan dispatches, workflow steps, research,
        background tasks) — not just workflow steps. This is intentionally
        broader than the old ExecutionRepository.count_active() which only
        counted workflow step executions.
        """
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(ExecutionRecord)
            .where(
                ExecutionRecord.status.in_(
                    [
                        ExecutionRecordStatus.PENDING,
                        ExecutionRecordStatus.RUNNING,
                    ]
                )
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_running_for_mission(self, mission_id: str) -> int:
        """Count RUNNING execution records for one mission.

        Narrower than count_active() — a single mission's in-flight runs,
        used to warn agents not to start new work while one is executing.
        """
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(ExecutionRecord)
            .where(
                ExecutionRecord.mission_id == mission_id,
                ExecutionRecord.status == ExecutionRecordStatus.RUNNING,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    # ---- Output extraction (Plan 71 — moved from ExecutionService) ----

    @staticmethod
    def extract_outputs(
        outcome_dict: dict | None,
        output_mapping: dict | None,
    ) -> dict[str, Any]:
        """Extract outputs from an ExecutionOutcome dict according to
        a workflow step's output_mapping.

        Works on the outcome dict directly (no model dependency).
        """
        if not output_mapping or not outcome_dict:
            return {}

        extracted: dict[str, Any] = {}

        summary_key = output_mapping.get("summary_key")
        if summary_key:
            extracted[summary_key] = outcome_dict.get("summary")

        field_mappings = output_mapping.get("field_mappings", [])
        raw_results = outcome_dict.get("task_results", [])

        by_task_id: dict[str, dict] = {}
        by_agent: dict[str, list[dict]] = {}
        if isinstance(raw_results, list):
            for tr in raw_results:
                if isinstance(tr, dict):
                    by_task_id[tr.get("task_id", "")] = tr.get(
                        "output_reference",
                        {},
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
                    # Promoted from WARNING to a hard step failure: a
                    # workflow that declares it needs a field but
                    # silently degrades when it isn't there lets the
                    # downstream agent fabricate output from nothing,
                    # which is exactly how a run can "complete" with
                    # a fabricated deliverable. Seed-time validation
                    # (workflow_validator) catches most cases; this
                    # is the runtime backstop.
                    available = list(task_output.keys()) if isinstance(task_output, dict) else []
                    raise WorkflowOutputMappingError(
                        f"Output mapping source field '{source_field}' "
                        f"not found on '{source_task}' output. "
                        f"Available: {sorted(available)}",
                        source_task=source_task,
                        source_field=source_field,
                        available_fields=sorted(available),
                    )
            else:
                raise WorkflowOutputMappingError(
                    f"Output mapping source task '{source_task}' not "
                    f"found in execution outcome",
                    source_task=source_task,
                    source_field=source_field,
                    available_fields=[],
                )

        return extracted
