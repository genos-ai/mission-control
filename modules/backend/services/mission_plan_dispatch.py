"""MissionPlanOrchestrator's dispatch entry point: one wave of a run's approved tasks.

Split out of mission_plan_orchestrator.py (Plan 84 Phase 5.2). The function
takes the owning MissionPlanOrchestrator instance (`orchestrator`) as an
explicit first argument to reach its repos/session/event_bus — mirroring the
Phase 5.1 pattern in workflow_run_steps/.

dispatch_approved is called externally as a bound method
(orchestrator.dispatch_approved(...) from the Temporal execute_mission
activity). Runs are started by MissionRunService (Plan 88 step 88.1.7);
each run has one ExecutionRecord, created by MissionRunService.begin, and
every wave updates it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.services import mission_plan_taskio
from modules.backend.services.mission_plan import remaining_plan_budget_usd

if TYPE_CHECKING:
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator


async def dispatch_approved(
    orchestrator: MissionPlanOrchestrator,
    mission_run_id: str,
    user_id: str,
    *,
    session_id: str,
    execution_record_id: str,
) -> dict:
    """Dispatch the run's approved tasks as a single wave.

    Plan 42 §10.1 + §10.5: filters the run's approved tasks into a
    TaskPlan, validates that the subset is a closed DAG (should always
    be true because approve_task transitively approves dependencies),
    and hands the derived TaskPlan to the existing dispatch pipeline via
    handle_mission(precomputed_plan=). Inline persistence updates the
    run's ExecutionRecord (execution_record_id); it never inserts one.

    After the wave completes, reads outcome.task_results to update each
    dispatched task row with its completion status and result summary.
    plan.total_spent_usd is incremented by the wave cost.

    Plan 42 §10.7 cumulative budget check: before dispatch, rejects
    if total_spent_usd >= budget_usd_ceiling (the default cap when NULL).

    Returns a dict with:
        outcome_status: "success" | "partial" | "failed"
        execution_record_id: the run's ExecutionRecord row (or None)
        dispatched_task_ids: list of task_ids that were sent to dispatch
        updated_task_ids: list of task_ids whose state was written back
        total_cost_usd: cost of this wave
        new_total_spent_usd: cumulative total after the wave
        outcome_json: the serialized ExecutionOutcome

    Raises:
        ValidationError: If the run has no approved tasks, nothing is in
            scope, the budget is exhausted, or the derived plan fails
            validation.
    """
    from modules.backend.agents.mission_control.mission_control import handle_mission

    run = await MissionRunRepository(orchestrator._session).get_by_id(mission_run_id)
    plan = await orchestrator._repo.get_by_id(run.plan_id)
    mission_plan_id = plan.id

    task_plan = mission_plan_taskio.materialize_task_plan(plan, mission_run_id=mission_run_id)

    # Budget check (Plan 42 §10.7)
    remaining = remaining_plan_budget_usd(plan)
    if remaining <= 0:
        raise ValidationError(
            f"Plan budget exhausted: spent "
            f"${plan.total_spent_usd:.4f} of "
            f"${plan.total_spent_usd + remaining:.4f} ceiling. "
            f"Increase budget_usd_ceiling to continue."
        )

    # Collect the run's approved task ids
    approved_states = await orchestrator._task_repo.list_by_run(
        mission_run_id,
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
    # in async mode.
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

    # Refresh plan and mission after the commit — all ORM attributes are
    # expired. Without refresh, any access to plan.gate_mode,
    # mission.execution_environment, etc. triggers MissingGreenlet.
    await orchestrator._session.refresh(plan)
    await orchestrator._session.refresh(mission)

    orchestrator._log_operation(
        "MissionPlan dispatching",
        plan_id=mission_plan_id,
        mission_run_id=mission_run_id,
        user_id=user_id,
        task_count=len(approved_task_ids),
        task_ids=sorted(approved_task_ids),
        gate_mode=plan.gate_mode.value,
        execution_record_id=execution_record_id,
    )

    # Build the gate reviewer from the plan's gate_mode (Plan 42 §10.4)
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
    budget = remaining

    from modules.backend.services.session import SessionService

    outcome = await handle_mission(
        execution_label=mission_run_id,
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
        execution_record_id=execution_record_id,
        mission_run_id=mission_run_id,
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
        mission_run_id=mission_run_id,
        outcome_status=(
            outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)
        ),
        execution_record_id=outcome.execution_record_id,
        run_cost_usd=outcome.total_cost_usd,
        total_spent_usd=plan.total_spent_usd,
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
        # activity. handle_mission already persists inside dispatch_approved,
        # but the workflow also persists independently for durability.
        "outcome_json": outcome.model_dump(mode="json"),
    }
