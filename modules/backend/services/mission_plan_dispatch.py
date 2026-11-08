"""MissionPlanOrchestrator's dispatch entry points: autonomous + approved-batch.

Split out of mission_plan_orchestrator.py (Plan 84 Phase 5.2). Pure move,
no behavior change. Functions take the owning MissionPlanOrchestrator
instance (`orchestrator`) as an explicit first argument to reach its
repos/session/event_bus — mirroring the Phase 5.1 pattern in
workflow_run_steps/.

dispatch_autonomous and dispatch_approved are called externally as
bound methods (orchestrator.dispatch_autonomous(...) from the
missions_plan endpoint, orchestrator.dispatch_approved(...) from the
Temporal execute_mission activity) — the orchestrator class keeps thin
delegating methods with these exact names so that external call surface
is unchanged; only the implementation lives here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.exceptions import ConflictError, ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.events.types import MissionPlanDispatchedEvent
from modules.backend.models.mission_plan import MissionPlanStatus
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.mission import MissionRepository
from modules.backend.services import mission_plan_supervisor, mission_plan_taskio
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

if TYPE_CHECKING:
    from modules.backend.models.mission_plan import MissionPlan
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator


async def dispatch_autonomous(
    orchestrator: MissionPlanOrchestrator,
    mission_plan_id: str,
    session_id: str | None = None,
) -> dict:
    """Start a Temporal MissionRunWorkflow for autonomous multi-wave execution.

    Returns a dict compatible with DispatchApprovedResponse. Raises if
    Temporal is unavailable — callers should let it propagate.

    The workflow handles the full supervisor loop: execute → evaluate →
    advance/refine/escalate → repeat until done or circuit-breaker trips.
    """
    plan = await orchestrator._repo.get_by_id(mission_plan_id)
    workflow_id = await start_temporal_run_workflow(
        orchestrator,
        plan,
        session_id,
    )

    approved_states = await orchestrator._task_repo.get_by_plan_id(
        mission_plan_id,
        status=TaskStatus.APPROVED,
    )
    return {
        "outcome_status": "dispatching",
        "dispatched_task_ids": [t.id for t in approved_states],
        "total_cost_usd": 0.0,
        "new_total_spent_usd": plan.total_spent_usd,
        "workflow_id": workflow_id,
    }


async def start_temporal_run_workflow(
    orchestrator: MissionPlanOrchestrator,
    plan: MissionPlan,
    session_id: str | None,
) -> str:
    """Start a MissionRunWorkflow via Temporal. Returns the workflow_id.

    Raises if Temporal is unavailable — callers should let it propagate.
    """
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.models import MissionWorkflowInput

    client = await get_temporal_client()
    config = get_app_config()

    mission = await MissionRepository(orchestrator._session).get_by_id(plan.mission_id)
    brief = mission.brief or mission.description or mission.name
    remaining_budget = (plan.budget_usd_ceiling or get_default_budget_usd()) - plan.total_spent_usd

    # Every execution must have a real session (P15).
    if not session_id:
        raise ValidationError(
            "session_id is required for dispatch. "
            "Callers must create a session before starting a workflow."
        )

    # Reset the DB supervisor counter at the start of each new
    # Temporal workflow — the workflow tracks its own iteration via
    # self._iteration and the DB counter is for observability only.
    # Without this reset, the counter grows across workflows and
    # misleadingly exceeds max_supervisor_iterations.
    plan.supervisor_iteration_count = 0
    await orchestrator._session.flush()

    workflow_input = MissionWorkflowInput(
        mission_run_id=plan.id,
        session_id=session_id,
        mission_brief=brief,
        roster_name=mission.default_roster or "default",
        mission_budget_usd=max(remaining_budget, 0.01),
        mission_id=plan.mission_id,
        execution_mode=mission.execution_environment,
    )

    workflow_id = mission_run_workflow_id(plan.id)
    try:
        await client.start_workflow(
            MissionRunWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=config.temporal.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        )
    except WorkflowAlreadyStartedError as exc:
        raise ConflictError(f"A mission run is already in progress for plan {plan.id}") from exc
    return workflow_id


async def dispatch_approved(
    orchestrator: MissionPlanOrchestrator,
    mission_plan_id: str,
    user_id: str,
    *,
    session_id: str | None = None,
    skip_post_run_supervisor: bool = False,
) -> dict:
    """Dispatch all currently-approved tasks as a single run.

    Plan 42 §10.1 + §10.5: filters approved tasks into a TaskPlan,
    validates that the subset is a closed DAG
    (should always be true because approve_task transitively
    approves dependencies), and hands the derived TaskPlan to the
    existing dispatch pipeline via handle_mission(precomputed_plan=).

    After the run completes, reads outcome.task_results to update
    each dispatched task_state row with its execution_record_id,
    task_execution_id, completion status, and result summary.
    plan.total_spent_usd is incremented by the run cost.

    Plan 42 §10.7 cumulative budget check: before dispatch, rejects
    if total_spent_usd >= budget_usd_ceiling (when set).

    Returns a dict with:
        outcome_status: "success" | "partial" | "failed"
        execution_record_id: the linked ExecutionRecord row (or None)
        dispatched_task_ids: list of task_ids that were sent to dispatch
        updated_task_ids: list of task_ids whose state was written back
        total_cost_usd: cost of this individual run
        new_total_spent_usd: cumulative total after the run

    Raises:
        ValidationError: If no tasks are approved, the plan is empty,
            the budget is exhausted, or the derived plan fails
            validation.
    """
    from modules.backend.agents.mission_control.mission_control import handle_mission

    plan = await orchestrator._repo.get_by_id(mission_plan_id)

    # Reconcile orphaned tasks before dispatch — if a prior dispatch
    # crashed after marking tasks RUNNING, those orphans would block
    # dependency validation. Move orphaned RUNNING → FAILED so the
    # user can retry them explicitly.
    from modules.backend.services.mission_plan_crash_recovery import (
        reconcile_orphaned_task_states,
    )

    await reconcile_orphaned_task_states(
        orchestrator._session,
        orchestrator._event_bus,
        plan_id=mission_plan_id,
    )

    task_plan = mission_plan_taskio.materialize_task_plan(plan)

    # Budget check (Plan 42 §10.7)
    if plan.budget_usd_ceiling is not None:
        remaining = plan.budget_usd_ceiling - plan.total_spent_usd
        if remaining <= 0:
            raise ValidationError(
                f"Plan budget exhausted: spent "
                f"${plan.total_spent_usd:.4f} of "
                f"${plan.budget_usd_ceiling:.4f} ceiling. "
                f"Increase budget_usd_ceiling to continue."
            )

    # Collect approved task ids
    approved_states = await orchestrator._task_repo.get_by_plan_id(
        mission_plan_id,
        status=TaskStatus.APPROVED,
    )
    if not approved_states:
        raise ValidationError(
            "No tasks are approved for dispatch. Approve tasks via " "the Plan tab before running."
        )
    approved_task_ids = {t.id for t in approved_states}

    # Derive the filtered TaskPlan. Approval is transitive (§10.2) so
    # the closure guarantee should hold — but verify and raise if not.
    # Dependencies that completed in prior runs are treated as satisfied.
    derived_plan = await mission_plan_taskio.derive_subset_task_plan(
        orchestrator,
        task_plan,
        approved_task_ids,
        mission_plan_id,
    )

    # Save plan attributes before commit — commit() expires all ORM
    # attributes and any subsequent access triggers MissingGreenlet
    # in async mode. We need these values between two commits
    # (here and inside create_early_execution_record).
    _plan_mission_id = plan.mission_id

    # Mark approved → running and commit immediately so the kanban
    # board shows the task in the "Running" column during execution.
    # We skip "queued" because handle_mission starts immediately —
    # there's no queue delay in the synchronous dispatch path.
    now = utc_now()
    for state in approved_states:
        state.status = TaskStatus.RUNNING
        state.last_attempt_at = now
    await orchestrator._session.commit()

    # Fetch mission for brief + session service
    mission = await MissionRepository(orchestrator._session).get_by_id(_plan_mission_id)
    brief = mission.brief or mission.description or mission.name

    # Create an early execution record so the run is visible in the
    # "runs" tab and the background-task badge while it executes.
    # persist_mission_results will UPDATE this record on completion.
    task_type = mission_plan_taskio.infer_task_type(derived_plan)
    early_record = await create_early_execution_record(
        orchestrator,
        mission_id=_plan_mission_id,
        plan_id=mission_plan_id,
        mission=mission,
        session_id=session_id,
        task_type=task_type,
        approved_task_ids=approved_task_ids,
    )
    early_record_id = early_record.id if early_record else None

    # Refresh plan and mission after all commits —
    # create_early_execution_record also commits, so all ORM
    # attributes are expired. Without refresh, any access to
    # plan.gate_mode, mission.execution_environment, etc.
    # triggers MissingGreenlet in async mode.
    await orchestrator._session.refresh(plan)
    await orchestrator._session.refresh(mission)

    orchestrator._log_operation(
        "MissionPlan dispatching",
        plan_id=mission_plan_id,
        user_id=user_id,
        task_count=len(approved_task_ids),
        task_ids=sorted(approved_task_ids),
        gate_mode=plan.gate_mode,
        execution_record_id=early_record_id,
    )

    # Build the gate reviewer from the plan's gate_mode (Plan 42 §10.4)
    gate_reviewer = None
    if plan.gate_mode:
        from modules.backend.agents.mission_control.gate import create_gate

        gate_reviewer = create_gate(
            mode_override=plan.gate_mode,
            event_bus=orchestrator._event_bus,
        )

    # Load outputs from prior waves so downstream tasks can resolve
    # from_upstream references to tasks that completed in earlier
    # dispatch_approved calls.
    prior_outputs = await mission_plan_taskio.load_prior_outputs(orchestrator, mission_plan_id)

    # Dispatch via the Phase 0 precomputed_plan path
    budget = plan.budget_usd_ceiling or get_default_budget_usd()
    if plan.budget_usd_ceiling is not None:
        budget = plan.budget_usd_ceiling - plan.total_spent_usd

    from modules.backend.services.session import SessionService

    outcome = await handle_mission(
        mission_run_id=mission_plan_id,
        mission_brief=brief,
        session_service=SessionService(orchestrator._session),  # type: ignore[arg-type]
        event_bus=orchestrator._event_bus,
        roster_name=mission.default_roster,
        mission_budget_usd=budget,
        session_id=session_id,
        mission_id=plan.mission_id,
        db_session=orchestrator._session,
        gate=gate_reviewer,
        execution_mode=mission.execution_environment or "local",
        precomputed_plan=derived_plan,
        mission_repo_root=mission.repo_root,
        prior_outputs=prior_outputs,
        execution_record_id=early_record_id,
    )

    # Write back task states from outcome (Plan 42 §10.5 batch write-back)
    updated_ids = await mission_plan_taskio.write_back_task_results(
        orchestrator,
        plan,
        outcome,
        dispatched_task_ids=approved_task_ids,
    )

    # Update cumulative cost (Plan 42 §10.7)
    plan.total_spent_usd += float(outcome.total_cost_usd or 0.0)
    await orchestrator._session.flush()

    orchestrator._log_operation(
        "MissionPlan dispatched",
        plan_id=mission_plan_id,
        outcome_status=(
            outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)
        ),
        execution_record_id=outcome.execution_record_id,
        run_cost_usd=outcome.total_cost_usd,
        total_spent_usd=plan.total_spent_usd,
    )

    await orchestrator._emit(
        plan.mission_id,
        MissionPlanDispatchedEvent(
            session_id=uuid.uuid4(),
            source="mission_plan_orchestrator",
            mission_id=plan.mission_id,
            plan_id=plan.id,
            execution_record_id=outcome.execution_record_id,
            dispatched_task_ids=sorted(approved_task_ids),
        ),
    )

    # When called from Temporal's execute_mission activity, skip the
    # inline supervisor — the MissionRunWorkflow handles the supervisor
    # loop, Director notifications, and plan status changes. Running
    # both causes double-evaluation and the inline one steals decisions.
    if not skip_post_run_supervisor:
        await orchestrator._session.refresh(plan, ["status"])
        if plan.status != MissionPlanStatus.ACTIVE:
            orchestrator._log_operation(
                "Skipping post-run supervisor — plan no longer active",
                plan_id=mission_plan_id,
                plan_status=plan.status,
            )
        else:
            await mission_plan_supervisor.post_run_supervisor(
                orchestrator,
                plan,
                outcome,
                session_id=session_id,
            )

    return {
        "outcome_status": (
            outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)
        ),
        "execution_record_id": outcome.execution_record_id,
        "dispatched_task_ids": sorted(approved_task_ids),
        "updated_task_ids": updated_ids,
        "total_cost_usd": float(outcome.total_cost_usd or 0.0),
        "new_total_spent_usd": plan.total_spent_usd,
        # Full serialized outcome for Temporal's persist_mission_outcome
        # activity (MissionRunWorkflow Step 2). handle_mission already
        # persists inside dispatch_approved, but the workflow also
        # persists independently for durability.
        "outcome_json": outcome.model_dump(mode="json"),
    }


async def create_early_execution_record(
    orchestrator: MissionPlanOrchestrator,
    mission_id: str,
    plan_id: str,
    mission,
    *,
    session_id: str | None,
    task_type: str,
    approved_task_ids: set[str],
):
    """Insert a 'running' ExecutionRecord before dispatch starts.

    Makes the run visible in the Runs tab and background-task badge
    while execution is in progress.  persist_mission_results will
    UPDATE this record with final results on completion.

    Accepts mission_id and plan_id as explicit strings (not from the
    plan ORM object) because the plan's attributes may be expired
    after a prior commit.
    """
    from modules.backend.models.execution_record import ExecutionRecord, ExecutionRecordStatus

    try:
        record = ExecutionRecord(
            session_id=session_id,
            status=ExecutionRecordStatus.RUNNING,
            mission_id=mission_id,
            roster_name=mission.default_roster,
            objective_statement=(mission.brief or mission.description or mission.name),
            task_type=task_type,
            task_params={
                "plan_id": plan_id,
                "task_ids": sorted(approved_task_ids),
            },
            started_at=utc_now(),
        )
        orchestrator._session.add(record)
        await orchestrator._session.commit()
        return record
    except SQLAlchemyError:
        await orchestrator._session.rollback()
        orchestrator._logger.warning(
            "Failed to create early execution record (non-fatal)",
            exc_info=True,
        )
        return None
