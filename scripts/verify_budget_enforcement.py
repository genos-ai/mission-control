#!/usr/bin/env python3
"""
Plan 46 Phase 1 work unit #4 — Budget Enforcement Stress Test.

Verifies the cumulative budget enforcement from Plan 42 §10.7 both
at the service layer (``MissionPlanService.dispatch_approved``) and
at the daemon query layer (``MissionPlanDaemon._find_ready_plan_ids``).

Exit criterion from Plan 46 §4 Phase 1:

    "Daemon refuses to dispatch a batch when
     (budget_usd_ceiling - total_spent_usd) is exhausted, and logs
     the refusal with a clear message."

What this script checks, against the real DB (no mocks):

  [A] Service-layer budget check (defensive, Plan 42 §10.7)

      A1. Plan with budget exhausted (spent == ceiling):
          `dispatch_approved` raises ValidationError containing
          "budget exhausted" in the message.
      A2. Plan with budget overshot (spent > ceiling) — this can
          happen when a prior run's actual cost slightly exceeded
          its nominal ceiling; the next dispatch must still refuse.
      A3. Plan with budget healthy (spent < ceiling) — the service
          does NOT block on budget; it proceeds to the next check
          (which fails on "no approved tasks" in this test because
          we don't set up a task_plan, but that's the expected
          downstream error and proves the budget check passed).
      A4. Plan with budget_usd_ceiling = None (unlimited) — same as
          A3. Budget check is skipped.

  [B] Daemon-layer query filter (performance + log-noise)

      B1. An exhausted plan is NOT returned by
          `_find_ready_plan_ids()`.
      B2. A healthy plan with approved tasks IS returned.
      B3. A plan with NULL budget_usd_ceiling IS returned.
      B4. A plan with budget exactly at the ceiling (total_spent_usd
          == budget_usd_ceiling) is NOT returned (strictly-less-than
          comparison in the SQL filter).

Usage:
    python scripts/verify_budget_enforcement.py [--verbose]

Exit codes:
    0  — all checks passed
    1  — one or more checks failed

Requirements:
    - Postgres running and reachable
    - At least one mission in the DB (the test plans attach to an
      existing mission; we don't fabricate users)

Re-runnable any number of times. Every row created by the script is
tagged with a unique run identifier and cleaned up on teardown.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

PASS = "✓"
FAIL = "✗"
SKIP = "⚠"


class BudgetEnforcementVerifier:
    """Runs the budget enforcement stress test against the real DB."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._run_tag = uuid.uuid4().hex[:8]
        # Track the test plans we create so teardown can remove them.
        self._test_plan_ids: list[str] = []
        # Remember the host mission so we can reattach its original plan
        # after teardown (we reserve the mission's plan slot for our
        # test rows — one plan per mission constraint).
        self._host_mission_id: str | None = None
        self._original_plan_id: str | None = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    {msg}")

    def _pass(self, check: str) -> None:
        print(f"  {PASS} {check}")

    def _fail(self, check: str, detail: str) -> None:
        print(f"  {FAIL} {check}: {detail}")
        self._failures.append(f"{check}: {detail}")

    def _skip(self, check: str, reason: str) -> None:
        print(f"  {SKIP} {check}: {reason} (skipped)")

    async def setup(self) -> bool:
        """Create test mission plan rows with varied budget configurations.

        We need FOUR distinct plans to test the full matrix. The
        ``mission_plans`` table has a one-plan-per-mission unique
        constraint, so we need four missions. Rather than fabricate
        missions + users (which hits user FKs), we find existing
        missions in the DB and attach test plans to them — but that
        collides with the unique constraint.

        The cleanest approach: create plans directly via the ORM with
        fresh mission_ids we make up for the test, bypassing the
        unique constraint because we're NOT linking to real missions.
        That breaks the FK though.

        The simplest robust approach that actually works: use the
        existing dev missions in the DB, which typically already have
        plans created lazily. Temporarily reassign their budget
        fields, run the test, then restore. But that mutates
        real data.

        Cleanest of all: use the single existing mission's plan for
        the service-layer check (scenario A), and for the daemon-
        layer check (scenario B) use a set of mission_plan rows with
        fake mission_ids pointing at rows we create on the fly under
        a test user. Too much setup.

        Pragmatic compromise taken here: for scenario A we do
        mutate-and-restore on the existing plan's budget fields. For
        scenario B we query real plans that happen to be in the DB
        and assert the filter's behaviour is consistent with their
        states (which is verifiable but less exhaustive). This avoids
        needing to create/delete missions or users, which would
        complicate the script significantly.
        """
        from sqlalchemy import select
        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission import Mission
        from modules.backend.repositories.mission_plan import MissionPlanRepository

        async with get_async_session() as db:
            result = await db.execute(select(Mission).limit(1))
            mission = result.scalar_one_or_none()
            if mission is None:
                print(f"\n{FAIL} Setup failed: no missions in DB.")
                return False
            self._host_mission_id = mission.id
            self._log(f"Using host mission: {mission.id} ({mission.name})")

            repo = MissionPlanRepository(db)
            plan = await repo.get_by_mission_id(mission.id)
            if plan is None:
                plan = await repo.create_for_mission(mission.id)
            self._original_plan_id = plan.id

            # Snapshot the current budget fields so teardown can
            # restore exactly what was there before.
            self._original_budget_ceiling = plan.budget_usd_ceiling
            self._original_total_spent = plan.total_spent_usd
            self._log(
                f"Snapshotted plan {plan.id} budget: "
                f"ceiling={self._original_budget_ceiling} "
                f"spent={self._original_total_spent}"
            )
            await db.commit()

        return True

    async def teardown(self) -> None:
        """Restore the original plan's budget fields."""
        if self._original_plan_id is None:
            return

        from modules.backend.core.database import get_async_session
        from modules.backend.repositories.mission_plan import MissionPlanRepository

        async with get_async_session() as db:
            repo = MissionPlanRepository(db)
            plan = await repo.get_by_id(self._original_plan_id)
            plan.budget_usd_ceiling = self._original_budget_ceiling
            plan.total_spent_usd = self._original_total_spent
            await db.commit()
        self._log("Restored original plan budget fields")

    async def _set_budget(self, ceiling: float | None, spent: float) -> None:
        """Mutate the test plan's budget fields for a scenario."""
        from modules.backend.core.database import get_async_session
        from modules.backend.repositories.mission_plan import MissionPlanRepository

        async with get_async_session() as db:
            repo = MissionPlanRepository(db)
            plan = await repo.get_by_id(self._original_plan_id)
            plan.budget_usd_ceiling = ceiling
            plan.total_spent_usd = spent
            await db.commit()

    # -------------------------------------------------------------------------
    # A: Service-layer budget check
    # -------------------------------------------------------------------------

    async def _call_dispatch_and_capture(self) -> tuple[bool, str]:
        """Call dispatch_approved and return (raised_validation, message).

        `raised_validation` is True if a ValidationError fired; the
        message is its string form. Any other exception propagates.
        """
        from modules.backend.core.database import get_async_session
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.services.mission_plan import MissionPlanService

        async with get_async_session() as db:
            svc = MissionPlanService(db)
            try:
                await svc.dispatch_approved(
                    self._original_plan_id,
                    user_id="verify-budget-test",
                )
                return (False, "dispatch_approved did not raise")
            except ValidationError as exc:
                return (True, str(exc))

    async def check_service_refuses_exhausted(self) -> None:
        """[A1] spent == ceiling → ValidationError 'budget exhausted'."""
        await self._set_budget(ceiling=5.00, spent=5.00)
        raised, msg = await self._call_dispatch_and_capture()
        if not raised:
            self._fail("A1: spent == ceiling raises ValidationError", msg)
            return
        if "budget exhausted" not in msg.lower():
            self._fail(
                "A1: exhaustion message clarity",
                f"expected 'budget exhausted' in msg, got: {msg[:200]}",
            )
            return
        self._log(f"  msg: {msg}")
        self._pass("A1: spent == ceiling is refused with clear 'budget exhausted' message")

    async def check_service_refuses_overshot(self) -> None:
        """[A2] spent > ceiling (overshoot) → ValidationError."""
        await self._set_budget(ceiling=5.00, spent=6.50)
        raised, msg = await self._call_dispatch_and_capture()
        if not raised:
            self._fail("A2: spent > ceiling raises ValidationError", msg)
            return
        if "budget exhausted" not in msg.lower():
            self._fail(
                "A2: overshoot message clarity",
                f"expected 'budget exhausted' in msg, got: {msg[:200]}",
            )
            return
        self._pass("A2: spent > ceiling (overshoot) is refused")

    async def check_service_allows_healthy(self) -> None:
        """[A3] spent < ceiling → budget check passes, fails on next step.

        The next step after the budget check is "No tasks are
        approved". Since our test plan has no approved tasks, we
        expect a ValidationError with 'no tasks are approved'. If
        instead we got the 'budget exhausted' message, the budget
        check is over-reaching.
        """
        await self._set_budget(ceiling=100.00, spent=5.00)
        raised, msg = await self._call_dispatch_and_capture()
        if not raised:
            self._fail(
                "A3: healthy budget lets request proceed",
                "expected ValidationError from 'no tasks approved' step, got no error",
            )
            return
        if "budget exhausted" in msg.lower():
            self._fail(
                "A3: healthy budget is NOT refused",
                f"budget check over-reached — msg was: {msg[:200]}",
            )
            return
        if "no tasks" not in msg.lower() and "approved" not in msg.lower():
            # Some other error — might be a test env issue
            self._fail(
                "A3: healthy-budget downstream error shape",
                f"unexpected error: {msg[:200]}",
            )
            return
        self._pass("A3: spent < ceiling passes budget check (fails on 'no approved tasks' as expected)")

    async def check_service_allows_null_ceiling(self) -> None:
        """[A4] budget_usd_ceiling = None → budget check is skipped."""
        await self._set_budget(ceiling=None, spent=0.00)
        raised, msg = await self._call_dispatch_and_capture()
        if not raised:
            self._fail(
                "A4: NULL ceiling proceeds past budget check",
                "expected ValidationError from 'no tasks approved', got no error",
            )
            return
        if "budget" in msg.lower():
            self._fail(
                "A4: NULL ceiling skips budget check",
                f"budget-related error with NULL ceiling: {msg[:200]}",
            )
            return
        self._pass("A4: NULL ceiling skips budget check entirely")

    # -------------------------------------------------------------------------
    # B: Daemon-layer query filter
    # -------------------------------------------------------------------------

    async def check_daemon_filter_excludes_exhausted(self) -> None:
        """[B1] _find_ready_plan_ids skips plans where spent >= ceiling."""
        # Make the test plan exhausted. We also need at least one
        # approved task state OR the plan would be filtered on the
        # secondary "has approved tasks" check. But since we're
        # testing the BUDGET filter specifically, we add a fake
        # approved row temporarily, then remove it.

        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission_plan import (
            MissionPlan,
            MissionPlanStatus,
            PlanTaskState,
            PlanTaskStatus,
        )
        from modules.backend.services.mission_plan_daemon import MissionPlanDaemon

        test_task_id = f"budget-test-{self._run_tag}-approved"

        # Step 1: plan exhausted + approved task present + status active
        # + gate_mode in autonomous/off → should NOT appear in ready list.
        await self._set_budget(ceiling=5.00, spent=5.00)
        async with get_async_session() as db:
            plan = await db.get(MissionPlan, self._original_plan_id)
            original_status = plan.status
            original_gate_mode = plan.gate_mode
            plan.status = MissionPlanStatus.ACTIVE.value
            plan.gate_mode = "autonomous"
            state = PlanTaskState(
                mission_plan_id=plan.id,
                task_id=test_task_id,
                status=PlanTaskStatus.APPROVED.value,
            )
            db.add(state)
            await db.commit()

        try:
            daemon = MissionPlanDaemon()
            ready = await daemon._find_ready_plan_ids()
            if self._original_plan_id in ready:
                self._fail(
                    "B1: exhausted plan excluded from _find_ready_plan_ids",
                    f"exhausted plan {self._original_plan_id} was returned",
                )
            else:
                self._pass("B1: exhausted plan excluded from daemon ready-list query")
        finally:
            # Cleanup: remove the fake approved task, restore plan state
            from sqlalchemy import delete

            async with get_async_session() as db:
                await db.execute(
                    delete(PlanTaskState).where(
                        PlanTaskState.mission_plan_id == self._original_plan_id,
                        PlanTaskState.task_id == test_task_id,
                    )
                )
                plan = await db.get(MissionPlan, self._original_plan_id)
                plan.status = original_status
                plan.gate_mode = original_gate_mode
                await db.commit()

    async def check_daemon_filter_allows_healthy(self) -> None:
        """[B2] _find_ready_plan_ids includes healthy plans with approved tasks."""
        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission_plan import (
            MissionPlan,
            MissionPlanStatus,
            PlanTaskState,
            PlanTaskStatus,
        )
        from modules.backend.services.mission_plan_daemon import MissionPlanDaemon

        test_task_id = f"budget-test-{self._run_tag}-healthy"

        await self._set_budget(ceiling=100.00, spent=5.00)
        async with get_async_session() as db:
            plan = await db.get(MissionPlan, self._original_plan_id)
            original_status = plan.status
            original_gate_mode = plan.gate_mode
            plan.status = MissionPlanStatus.ACTIVE.value
            plan.gate_mode = "autonomous"
            state = PlanTaskState(
                mission_plan_id=plan.id,
                task_id=test_task_id,
                status=PlanTaskStatus.APPROVED.value,
            )
            db.add(state)
            await db.commit()

        try:
            daemon = MissionPlanDaemon()
            ready = await daemon._find_ready_plan_ids()
            if self._original_plan_id in ready:
                self._pass("B2: healthy plan with approved task is in daemon ready-list")
            else:
                self._fail(
                    "B2: healthy plan included",
                    f"plan {self._original_plan_id} was not returned (got {len(ready)} plans)",
                )
        finally:
            from sqlalchemy import delete

            async with get_async_session() as db:
                await db.execute(
                    delete(PlanTaskState).where(
                        PlanTaskState.mission_plan_id == self._original_plan_id,
                        PlanTaskState.task_id == test_task_id,
                    )
                )
                plan = await db.get(MissionPlan, self._original_plan_id)
                plan.status = original_status
                plan.gate_mode = original_gate_mode
                await db.commit()

    async def check_daemon_filter_null_ceiling(self) -> None:
        """[B3] _find_ready_plan_ids includes plans with NULL budget_usd_ceiling."""
        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission_plan import (
            MissionPlan,
            MissionPlanStatus,
            PlanTaskState,
            PlanTaskStatus,
        )
        from modules.backend.services.mission_plan_daemon import MissionPlanDaemon

        test_task_id = f"budget-test-{self._run_tag}-null"

        await self._set_budget(ceiling=None, spent=999.00)
        async with get_async_session() as db:
            plan = await db.get(MissionPlan, self._original_plan_id)
            original_status = plan.status
            original_gate_mode = plan.gate_mode
            plan.status = MissionPlanStatus.ACTIVE.value
            plan.gate_mode = "autonomous"
            state = PlanTaskState(
                mission_plan_id=plan.id,
                task_id=test_task_id,
                status=PlanTaskStatus.APPROVED.value,
            )
            db.add(state)
            await db.commit()

        try:
            daemon = MissionPlanDaemon()
            ready = await daemon._find_ready_plan_ids()
            if self._original_plan_id in ready:
                self._pass("B3: NULL ceiling plan is in daemon ready-list (unlimited budget)")
            else:
                self._fail(
                    "B3: NULL ceiling plan included",
                    f"plan {self._original_plan_id} was not returned",
                )
        finally:
            from sqlalchemy import delete

            async with get_async_session() as db:
                await db.execute(
                    delete(PlanTaskState).where(
                        PlanTaskState.mission_plan_id == self._original_plan_id,
                        PlanTaskState.task_id == test_task_id,
                    )
                )
                plan = await db.get(MissionPlan, self._original_plan_id)
                plan.status = original_status
                plan.gate_mode = original_gate_mode
                await db.commit()

    async def check_daemon_filter_exact_ceiling(self) -> None:
        """[B4] spent == ceiling (exact) is still excluded (strict <)."""
        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission_plan import (
            MissionPlan,
            MissionPlanStatus,
            PlanTaskState,
            PlanTaskStatus,
        )
        from modules.backend.services.mission_plan_daemon import MissionPlanDaemon

        test_task_id = f"budget-test-{self._run_tag}-exact"

        await self._set_budget(ceiling=10.00, spent=10.00)
        async with get_async_session() as db:
            plan = await db.get(MissionPlan, self._original_plan_id)
            original_status = plan.status
            original_gate_mode = plan.gate_mode
            plan.status = MissionPlanStatus.ACTIVE.value
            plan.gate_mode = "autonomous"
            state = PlanTaskState(
                mission_plan_id=plan.id,
                task_id=test_task_id,
                status=PlanTaskStatus.APPROVED.value,
            )
            db.add(state)
            await db.commit()

        try:
            daemon = MissionPlanDaemon()
            ready = await daemon._find_ready_plan_ids()
            if self._original_plan_id in ready:
                self._fail(
                    "B4: exact-ceiling plan excluded (strict less-than)",
                    "plan was returned — the SQL filter is <= instead of <",
                )
            else:
                self._pass("B4: spent == ceiling excluded (strict less-than comparison)")
        finally:
            from sqlalchemy import delete

            async with get_async_session() as db:
                await db.execute(
                    delete(PlanTaskState).where(
                        PlanTaskState.mission_plan_id == self._original_plan_id,
                        PlanTaskState.task_id == test_task_id,
                    )
                )
                plan = await db.get(MissionPlan, self._original_plan_id)
                plan.status = original_status
                plan.gate_mode = original_gate_mode
                await db.commit()

    # -------------------------------------------------------------------------
    # Runner
    # -------------------------------------------------------------------------

    async def run(self) -> bool:
        print(f"\nPlan 46 Phase 1 — Budget Enforcement Stress Test (run_tag={self._run_tag})")
        print("=" * 70)

        print("\n[Setup] Snapshotting test plan budget fields...")
        if not await self.setup():
            return False

        print("\n[A] Service-layer budget check (MissionPlanService.dispatch_approved)")
        await self.check_service_refuses_exhausted()
        await self.check_service_refuses_overshot()
        await self.check_service_allows_healthy()
        await self.check_service_allows_null_ceiling()

        print("\n[B] Daemon-layer query filter (MissionPlanDaemon._find_ready_plan_ids)")
        await self.check_daemon_filter_excludes_exhausted()
        await self.check_daemon_filter_allows_healthy()
        await self.check_daemon_filter_null_ceiling()
        await self.check_daemon_filter_exact_ceiling()

        print("\n" + "=" * 70)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        print("PASSED — all budget enforcement checks passed")
        return True


async def _main(verbose: bool) -> int:
    verifier = BudgetEnforcementVerifier(verbose=verbose)
    try:
        passed = await verifier.run()
    finally:
        try:
            await verifier.teardown()
        except Exception as exc:
            print(f"\n{FAIL} Teardown failed: {exc}")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show debug details")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.verbose)))


if __name__ == "__main__":
    main()
