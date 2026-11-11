"""Per-task execution bookkeeping for MissionRunWorkflow (Plan 88 step 88.2.4).

The ``execute_plan_task`` activity runs one approved task in two short
transactions around the agent call (contracts 3.1.9):

- ``claim`` locks the task row, applies the replay rules, moves the task to
  RUNNING and commits. No lock is held across the agent call.
- ``record`` locks the row again, re-checks the idempotency key and writes the
  task execution, the context updates, the task transition and the failure
  record in one transaction. The UNIQUE ``task_executions.idempotency_key``
  arbitrates between concurrent attempts.

``retry_count`` is never touched here; ``MissionPlanService.retry_task`` is
its only increment. This module imports nothing from ``modules.backend.agents``.
"""

import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import MissionRunStateError, NotFoundError, ValidationError
from modules.backend.core.failure_classification import get_failure_classifier
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import TaskExecution
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.execution_outcome import TaskResult
from modules.backend.schemas.execution_outcome import TaskStatus as OutcomeStatus
from modules.backend.schemas.task_failure import FailureClass
from modules.backend.schemas.task_plan import TaskDefinition
from modules.backend.services.base import BaseService
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_artifact import MissionArtifactService
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_plan_taskio import task_definition_from_row
from modules.backend.services.task_result_persistence import persist_task_result
from modules.backend.temporal.mission_run_models import ExecuteTaskResult

# Execution environment of a mission whose execution_environment is NULL (models/mission.py).
_DEFAULT_EXECUTION_MODE = "local"
_IDEMPOTENCY_CONSTRAINT = "uq_task_executions_idempotency_key"

_OUTCOME_TO_TASK: dict[OutcomeStatus, TaskStatus] = {
    OutcomeStatus.SUCCESS: TaskStatus.COMPLETED,
    OutcomeStatus.FAILED: TaskStatus.FAILED,
    OutcomeStatus.TIMEOUT: TaskStatus.FAILED,
    OutcomeStatus.SKIPPED: TaskStatus.SKIPPED,
}
_FINISHED = frozenset({TaskStatus.COMPLETED, TaskStatus.SKIPPED})
_TIERS = ("tier_1", "tier_2", "tier_3")


def idempotency_key(mission_run_id: str, task_id: str, retry_count: int) -> str:
    """The task attempt's idempotency key (contracts 3.1.8)."""
    return f"{mission_run_id}:{task_id}:{retry_count}"


def _verification_failed(status: str, verification_outcome: dict | None) -> bool:
    """A failed attempt whose verification has a failing tier."""
    if status != TaskStatus.FAILED.value or not verification_outcome:
        return False
    return any((verification_outcome.get(tier) or {}).get("status") == "fail" for tier in _TIERS)


def _stored_result(row: TaskExecution, fallback_reason: str | None) -> ExecuteTaskResult:
    """Rebuild an attempt's ExecuteTaskResult from its task_executions row.

    The row has no failure_reason column: the summary comes from failure_json,
    or from the task row when retention has cleared failure_json.
    """
    status = row.status.value
    failed = status == TaskStatus.FAILED.value
    summary = (row.failure_json or {}).get("summary") or fallback_reason
    return ExecuteTaskResult(
        task_id=row.task_id,
        status=status,
        verification_failed=_verification_failed(status, row.verification_outcome),
        cost_usd=float(row.cost_usd or 0.0),
        idempotent_replay=True,
        failure_reason=summary if failed else None,
        failure_origin=row.failure_origin.value if row.failure_origin is not None else None,
        failure_class=row.failure_class.value if row.failure_class is not None else None,
        failure_fingerprint=row.failure_fingerprint,
    )


def _finished_task_result(task: Task) -> ExecuteTaskResult:
    """Replay for a COMPLETED or SKIPPED task with no row under the current key."""
    return ExecuteTaskResult(
        task_id=task.id,
        status=task.status.value,
        verification_failed=False,
        cost_usd=float(task.cost_usd or 0.0),
        idempotent_replay=True,
        failure_reason=task.failure_reason,
        failure_origin=None,
        failure_class=None,
        failure_fingerprint=None,
    )


@dataclass
class TaskClaim:
    """What claim decided: execute the task, or replay a stored result."""

    outcome: Literal["execute", "replay"]
    idempotency_key: str
    task_definition: TaskDefinition | None  # "execute" only
    stored: ExecuteTaskResult | None  # "replay" only
    mission_id: str
    execution_mode: str
    mission_repo_root: str | None


class RunTaskExecutionService(BaseService):
    """Claim, record, cancel and resolve one task of a mission run."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tasks = TaskRepository(session)
        self._executions = ExecutionRecordRepository(session)
        self._missions = MissionRepository(session)

    async def _locked_task(self, mission_run_id: str, task_id: str) -> Task:
        task = await self._tasks.get_in_run(task_id, mission_run_id, for_update=True)
        if task is None:
            raise MissionRunStateError(f"Task {task_id} does not belong to run {mission_run_id}")
        return task

    async def claim(self, mission_run_id: str, task_id: str) -> TaskClaim:
        """Transaction A: decide between replay and execution; RUNNING on execute."""
        task = await self._locked_task(mission_run_id, task_id)
        key = idempotency_key(mission_run_id, task_id, task.retry_count)
        mission = await self._missions.get_by_id(task.mission_id)
        mission_id = mission.id
        execution_mode = mission.execution_environment or _DEFAULT_EXECUTION_MODE
        repo_root = mission.repo_root

        def _claim(
            outcome: Literal["execute", "replay"],
            definition: TaskDefinition | None,
            stored: ExecuteTaskResult | None,
        ) -> TaskClaim:
            return TaskClaim(
                outcome=outcome,
                idempotency_key=key,
                task_definition=definition,
                stored=stored,
                mission_id=mission_id,
                execution_mode=execution_mode,
                mission_repo_root=repo_root,
            )

        existing = await self._executions.get_task_execution_by_key(key)
        if existing is not None:
            stored = _stored_result(existing, task.failure_reason)
            await self._session.rollback()
            return _claim("replay", None, stored)
        if task.status in _FINISHED:
            stored = _finished_task_result(task)
            await self._session.rollback()
            return _claim("replay", None, stored)

        if task.status == TaskStatus.APPROVED:
            task.transition_status(TaskStatus.QUEUED)
        if task.status == TaskStatus.QUEUED:
            task.transition_status(TaskStatus.RUNNING)
        if task.status != TaskStatus.RUNNING:
            raise MissionRunStateError(f"Task {task_id} cannot run from status {task.status.value}")
        task.last_attempt_at = utc_now()
        definition = task_definition_from_row(task)
        await self._session.commit()
        self._log_operation(
            "Run task claimed", mission_run_id=mission_run_id, task_id=task_id, key=key
        )
        return _claim("execute", definition, None)

    async def record(
        self,
        *,
        mission_run_id: str,
        task_id: str,
        idempotency_key: str,
        execution_record_id: str,
        task_result_json: dict,
    ) -> ExecuteTaskResult:
        """Transaction B: write the attempt once; a duplicate returns the first write."""
        task_result = TaskResult.model_validate(task_result_json)
        if task_result.task_id != task_id:
            raise MissionRunStateError(
                f"Result for task {task_result.task_id} recorded against task {task_id}"
            )
        task = await self._locked_task(mission_run_id, task_id)
        existing = await self._executions.get_task_execution_by_key(idempotency_key)
        if existing is not None:
            stored = _stored_result(existing, task.failure_reason)
            await self._session.rollback()
            return stored
        try:
            result = await self._write_attempt(
                task,
                task_result,
                mission_run_id=mission_run_id,
                idempotency_key=idempotency_key,
                execution_record_id=execution_record_id,
            )
            await self._session.commit()
        except IntegrityError as exc:
            if _IDEMPOTENCY_CONSTRAINT not in str(exc.orig):
                raise
            await self._session.rollback()
            return await self._replay_after_race(mission_run_id, task_id, idempotency_key)
        self._log_operation(
            "Run task recorded",
            mission_run_id=mission_run_id,
            task_id=task_id,
            status=result.status,
            key=idempotency_key,
        )
        return result

    async def _replay_after_race(
        self, mission_run_id: str, task_id: str, key: str
    ) -> ExecuteTaskResult:
        """Another attempt recorded first: return its row."""
        row = await self._executions.get_task_execution_by_key(key)
        if row is None:
            raise MissionRunStateError(f"Idempotency conflict on {key} but no row was recorded")
        task = await self._tasks.get_in_run(task_id, mission_run_id)
        stored = _stored_result(row, task.failure_reason if task is not None else None)
        await self._session.rollback()
        return stored

    async def _write_attempt(
        self,
        task: Task,
        task_result: TaskResult,
        *,
        mission_run_id: str,
        idempotency_key: str,
        execution_record_id: str,
    ) -> ExecuteTaskResult:
        mission_id = task.mission_id
        target = _OUTCOME_TO_TASK[task_result.status]
        await persist_task_result(
            ExecutionPersistenceService(self._session),
            execution_record_id=execution_record_id,
            task_result=task_result,
            mission_id=mission_id,
            domain_tags=task.domain_tags or None,
            mission_run_id=mission_run_id,
            idempotency_key=idempotency_key,
            artifact_svc=MissionArtifactService(self._session),
        )
        if task_result.status == OutcomeStatus.SUCCESS and task_result.context_updates:
            _, errors = await MissionContextManager(self._session).apply_updates(
                mission_id,
                task_result.context_updates,
                agent_id=task_result.agent_name,
                mission_id_ref=mission_id,
                task_id=task.id,
                mission_run_id=mission_run_id,
            )
            if errors:
                self._log_operation(
                    "Run task context updates partly rejected",
                    task_id=task.id,
                    errors=errors,
                )
        try:
            task.transition_status(target)
        except ValueError as exc:
            raise MissionRunStateError(str(exc)) from exc
        task.cost_usd = float(task_result.cost_usd or 0.0)
        task.duration_seconds = float(task_result.duration_seconds or 0.0)
        if target == TaskStatus.COMPLETED:
            task.result_summary = json.dumps(task_result.output_reference, default=str)
        self._tasks.set_failure(task, task_result.failure)
        await self._session.flush()

        failure = task_result.failure
        verification = task_result.verification_outcome.model_dump()
        return ExecuteTaskResult(
            task_id=task.id,
            status=target.value,
            verification_failed=_verification_failed(target.value, verification),
            cost_usd=float(task_result.cost_usd or 0.0),
            idempotent_replay=False,
            failure_reason=failure.summary if failure is not None else None,
            failure_origin=failure.origin.value if failure is not None else None,
            failure_class=failure.failure_class.value if failure is not None else None,
            failure_fingerprint=failure.fingerprint if failure is not None else None,
        )

    async def mark_cancelled(self, mission_run_id: str, task_id: str) -> None:
        """RUNNING to FAILED with control(CANCELLED); a task no longer RUNNING is left alone."""
        task = await self._locked_task(mission_run_id, task_id)
        if task.status != TaskStatus.RUNNING:
            self._log_operation(
                "Cancelled run task was not running",
                task_id=task_id,
                status=task.status.value,
            )
            await self._session.rollback()
            return
        task.transition_status(TaskStatus.FAILED)
        self._tasks.set_failure(
            task, get_failure_classifier().control(FailureClass.CANCELLED, "cancelled")
        )
        await self._session.commit()

    async def resolve_failed(
        self, mission_run_id: str, task_id: str, action: Literal["retry", "skip"]
    ) -> None:
        """A gate's answer to a failed task: retry it (APPROVED) or skip it (SKIPPED)."""
        task = await self._tasks.get_in_run(task_id, mission_run_id, for_update=True)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found in run {mission_run_id}")
        if action == "retry":
            mission = await self._missions.get_by_id(task.mission_id)
            await MissionPlanService(self._session).retry_task(
                task.plan_id, task_id, user_id=mission.owner_id
            )
        elif action == "skip":
            try:
                task.transition_status(TaskStatus.SKIPPED)
            except ValueError as exc:
                raise MissionRunStateError(str(exc)) from exc
            # The attempt's failure stays on its task_executions row.
            self._tasks.set_failure(task, None)
        else:
            raise ValidationError(f"Unknown failed-task action: {action!r}")
        await self._session.commit()
        self._log_operation(
            "Run task resolved", mission_run_id=mission_run_id, task_id=task_id, action=action
        )
