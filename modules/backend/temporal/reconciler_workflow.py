"""ReconcilerWorkflow (Plan 88 step 88.0.10, contract 3.3.2).

Started by the `system-reconciler` schedule. Reads no config: every policy
arrives in ReconcilerInput, built by system_schedules.py.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.activity_options import activity_kwargs
    from modules.backend.temporal.mission_run_models import (
        ReconcileInput,
        ReconcilerInput,
        ReconcileStats,
    )
    from modules.backend.temporal.reconciler_activities import reconcile_mission_runs


@workflow.defn
class ReconcilerWorkflow:
    @workflow.run
    async def run(self, inp: ReconcilerInput) -> ReconcileStats:
        return await workflow.execute_activity(
            reconcile_mission_runs,
            ReconcileInput(orphan_grace_seconds=inp.orphan_grace_seconds),
            **activity_kwargs(inp.activity),
        )
