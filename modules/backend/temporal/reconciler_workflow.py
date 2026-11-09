"""ReconcilerWorkflow (Plan 88 steps 88.0.10 and 88.1.10, contract 3.3.2).

Started by the `system-reconciler` schedule. Reads no config: every policy
arrives in ReconcilerInput, built by system_schedules.py. Runs
reconcile_mission_runs, then sync_mission_schedules, whose stats fill
ReconcileStats.schedule_sync.
"""

import dataclasses

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.activity_options import activity_kwargs
    from modules.backend.temporal.mission_run_models import (
        ReconcileInput,
        ReconcilerInput,
        ReconcileStats,
    )
    from modules.backend.temporal.reconciler_activities import (
        reconcile_mission_runs,
        sync_mission_schedules,
    )


@workflow.defn
class ReconcilerWorkflow:
    @workflow.run
    async def run(self, inp: ReconcilerInput) -> ReconcileStats:
        stats = await workflow.execute_activity(
            reconcile_mission_runs,
            ReconcileInput(orphan_grace_seconds=inp.orphan_grace_seconds),
            **activity_kwargs(inp.activity),
        )
        sync = await workflow.execute_activity(
            sync_mission_schedules, None, **activity_kwargs(inp.activity)
        )
        return dataclasses.replace(stats, schedule_sync=sync)
