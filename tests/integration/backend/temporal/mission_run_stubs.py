"""Stub activities for the MissionRunWorkflow integration tests (Plan 88 steps 88.2.6, 88.3.8).

Each stub is registered under the real activity name. Stubs read their script
from the module-level ``SCRIPT`` and append ``(activity name, input)`` to the
module-level ``CALLS`` list; ``reset()`` restores both between tests.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from modules.backend.temporal.mission_run_models import (
    BeginRunInput,
    BeginRunResult,
    CompactContextInput,
    CompactContextResult,
    DigestResult,
    DirectorTurnInput,
    ExecuteTaskInput,
    ExecuteTaskResult,
    FinaliseRunInput,
    FinaliseRunResult,
    PlanRunInput,
    PlanRunResult,
    ResolveTaskInput,
    RunTaskGraph,
    SupervisorFollowupInput,
    WriteDigestInput,
)
from modules.backend.temporal.supervisor_activities import PostRunEvalInput, PostRunEvalResult

SESSION_ID = "11111111-1111-1111-1111-111111111111"
RECORD_ID = "22222222-2222-2222-2222-222222222222"


def completed(task_id: str, cost_usd: float = 0.0) -> ExecuteTaskResult:
    return ExecuteTaskResult(
        task_id=task_id,
        status="completed",
        verification_failed=False,
        cost_usd=cost_usd,
        idempotent_replay=False,
        failure_reason=None,
        failure_origin=None,
        failure_class=None,
        failure_fingerprint=None,
    )


def failed(
    task_id: str,
    *,
    cost_usd: float = 0.0,
    reason: str = "boom",
    origin: str = "agent",
    failure_class: str = "agent_reported_failure",
    fingerprint: str = "f1",
    verification_failed: bool = False,
) -> ExecuteTaskResult:
    return ExecuteTaskResult(
        task_id=task_id,
        status="failed",
        verification_failed=verification_failed,
        cost_usd=cost_usd,
        idempotent_replay=False,
        failure_reason=reason,
        failure_origin=origin,
        failure_class=failure_class,
        failure_fingerprint=fingerprint,
    )


def graph(*layers: list[str], proposed: int = 0) -> RunTaskGraph:
    approved = sum(len(layer) for layer in layers)
    return RunTaskGraph(layers=list(layers), proposed=proposed, approved=approved, running=0)


@dataclass
class Script:
    graphs: list[RunTaskGraph] = field(default_factory=list)  # the last one repeats
    actions: list[str] = field(default_factory=list)  # the last one repeats
    task_results: dict[str, list[ExecuteTaskResult]] = field(default_factory=dict)
    task_errors: dict[str, Exception] = field(default_factory=dict)
    task_delay_seconds: float = 0.0
    task_hook: Callable[[ExecuteTaskInput], Awaitable[None]] | None = None
    compaction_error: Exception | None = None
    running: int = 0
    max_running: int = 0
    activity_timeouts: list[tuple[timedelta | None, timedelta | None]] = field(default_factory=list)


SCRIPT = Script()
CALLS: list[tuple[str, Any]] = []


def reset() -> None:
    SCRIPT.__init__()
    CALLS.clear()


def calls(name: str) -> list[Any]:
    return [arg for called, arg in CALLS if called == name]


def _next(items: list) -> Any:
    return items.pop(0) if len(items) > 1 else items[0]


@activity.defn(name="begin_mission_run")
async def begin_stub(inp: BeginRunInput) -> BeginRunResult:
    CALLS.append(("begin_mission_run", inp))
    return BeginRunResult(
        session_id=SESSION_ID,
        execution_record_id=RECORD_ID,
        context_version_start=0,
        gate_mode="autonomous",
        previous_run_id=None,
    )


@activity.defn(name="plan_mission_run")
async def plan_stub(inp: PlanRunInput) -> PlanRunResult:
    CALLS.append(("plan_mission_run", inp))
    return PlanRunResult(task_ids=[], status="planned", detail=None)


@activity.defn(name="fetch_run_task_graph")
async def graph_stub(mission_run_id: str) -> RunTaskGraph:
    CALLS.append(("fetch_run_task_graph", mission_run_id))
    return _next(SCRIPT.graphs)


@activity.defn(name="execute_plan_task")
async def execute_stub(inp: ExecuteTaskInput) -> ExecuteTaskResult:
    CALLS.append(("execute_plan_task", inp))
    info = activity.info()
    SCRIPT.activity_timeouts.append((info.heartbeat_timeout, info.start_to_close_timeout))
    SCRIPT.running += 1
    SCRIPT.max_running = max(SCRIPT.max_running, SCRIPT.running)
    try:
        if SCRIPT.task_hook is not None:
            await SCRIPT.task_hook(inp)
        if SCRIPT.task_delay_seconds:
            await asyncio.sleep(SCRIPT.task_delay_seconds)
        error = SCRIPT.task_errors.get(inp.task_id)
        if error is not None:
            raise error
        queued = SCRIPT.task_results.get(inp.task_id)
        result = queued.pop(0) if queued else completed(inp.task_id)
        CALLS.append(("execute_plan_task_done", inp.task_id))
        return result
    finally:
        SCRIPT.running -= 1


@activity.defn(name="resolve_failed_task")
async def resolve_stub(inp: ResolveTaskInput) -> None:
    CALLS.append(("resolve_failed_task", inp))


@activity.defn(name="evaluate_post_run")
async def evaluate_stub(inp: PostRunEvalInput) -> PostRunEvalResult:
    CALLS.append(("evaluate_post_run", inp))
    return PostRunEvalResult(action=_next(SCRIPT.actions), reason="because")


@activity.defn(name="fire_supervisor_followups")
async def followups_stub(inp: SupervisorFollowupInput) -> None:
    CALLS.append(("fire_supervisor_followups", inp))


@activity.defn(name="check_plan_active")
async def plan_active_stub(mission_id: str) -> bool:
    CALLS.append(("check_plan_active", mission_id))
    return True


@activity.defn(name="approve_run_proposed_tasks")
async def approve_stub(mission_run_id: str) -> int:
    CALLS.append(("approve_run_proposed_tasks", mission_run_id))
    return 0


@activity.defn(name="start_director_turn")
async def director_stub(inp: DirectorTurnInput) -> str:
    CALLS.append(("start_director_turn", inp))
    return "director-turn"


@activity.defn(name="compact_mission_context")
async def compact_stub(inp: CompactContextInput) -> CompactContextResult:
    CALLS.append(("compact_mission_context", inp))
    if SCRIPT.compaction_error is not None:
        raise SCRIPT.compaction_error
    return CompactContextResult(compacted=False, from_bytes=0, to_bytes=0)


@activity.defn(name="write_run_digest")
async def digest_stub(inp: WriteDigestInput) -> DigestResult:
    CALLS.append(("write_run_digest", inp))
    generator = "deterministic" if inp.force_deterministic else "agent"
    return DigestResult(digest_id="33333333-3333-3333-3333-333333333333", generator=generator)


@activity.defn(name="finalise_mission_run")
async def finalise_stub(inp: FinaliseRunInput) -> FinaliseRunResult:
    CALLS.append(("finalise_mission_run", inp))
    return FinaliseRunResult(cost_usd=0.0, notification=None)


def non_retryable(message: str) -> ApplicationError:
    return ApplicationError(message, type="TaskInfraError", non_retryable=True)


ACTIVITIES = [
    begin_stub,
    plan_stub,
    graph_stub,
    execute_stub,
    resolve_stub,
    evaluate_stub,
    followups_stub,
    plan_active_stub,
    approve_stub,
    director_stub,
    compact_stub,
    digest_stub,
    finalise_stub,
]
