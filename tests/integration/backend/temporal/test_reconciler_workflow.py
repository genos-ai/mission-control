"""ReconcilerWorkflow (Plan 88 steps 88.0.10 and 88.1.10).

Runs the real workflow in a time-skipping Temporal environment with stubs
registered under the real activity names. The stubs record their calls in
order and return fixed stats.
"""

import dataclasses
import uuid

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.config_snapshots import config_hash, policy_snapshot
    from modules.backend.temporal.mission_run_models import (
        ReconcileInput,
        ReconcilerInput,
        ReconcileStats,
        ScheduleSyncStats,
    )
    from modules.backend.temporal.reconciler_workflow import ReconcilerWorkflow

_received: list[ReconcileInput] = []
_order: list[str] = []

_STATS = ReconcileStats(
    examined_tasks=3,
    examined_execution_records=2,
    examined_workflow_runs=1,
    failed_tasks=1,
    failed_execution_records=1,
    failed_workflow_runs=0,
    left_running=2,
    left_in_process=1,
    schedule_sync=None,
)


_SYNC = ScheduleSyncStats(synced=4, failed=1, deleted_orphans=2, completed=1)


@activity.defn(name="reconcile_mission_runs")
async def reconcile_mission_runs_stub(input: ReconcileInput) -> ReconcileStats:
    _order.append("reconcile_mission_runs")
    _received.append(input)
    return _STATS


@activity.defn(name="sync_mission_schedules")
async def sync_mission_schedules_stub(mission_id: str | None) -> ScheduleSyncStats:
    _order.append("sync_mission_schedules")
    assert mission_id is None
    return _SYNC


async def _run_workflow() -> ReconcileStats:
    _received.clear()
    _order.clear()
    temporal = get_app_config().temporal
    inp = ReconcilerInput(
        config_hash="",
        orphan_grace_seconds=600,
        activity=policy_snapshot(temporal.reconciler.activity),
    )
    inp = ReconcilerInput(
        config_hash=config_hash(inp),
        orphan_grace_seconds=inp.orphan_grace_seconds,
        activity=inp.activity,
    )

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue=temporal.task_queue,
            workflows=[ReconcilerWorkflow],
            activities=[reconcile_mission_runs_stub, sync_mission_schedules_stub],
        ):
            result = await env.client.execute_workflow(
                ReconcilerWorkflow.run,
                inp,
                id=f"system-reconciler-test-{uuid.uuid4().hex[:8]}",
                task_queue=temporal.task_queue,
            )
    finally:
        await env.shutdown()
    return result


async def test_workflow_runs_activity_with_grace():
    result = await _run_workflow()

    assert _received == [ReconcileInput(orphan_grace_seconds=600)]
    assert result == dataclasses.replace(_STATS, schedule_sync=_SYNC)


async def test_runs_reconcile_then_sync():
    result = await _run_workflow()

    assert _order == ["reconcile_mission_runs", "sync_mission_schedules"]
    assert result.schedule_sync == _SYNC
