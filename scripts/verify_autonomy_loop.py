#!/usr/bin/env python3
"""
Plan 51 Phase F — Autonomy Loop End-to-End Verification.

Verifies the full post-run gate checkpoint, decision matrix, circuit
breakers, idempotency, and event chain that Plan 51 Phases A–E
assembled.

Tests the reviewer DIRECTLY with synthetic GateContext inputs (no
real LLM calls for branches 1–7). Branch #8 (Haiku classification)
is tested only as a fallthrough-to-ESCALATE since the Haiku agent
requires API keys and real token spend — that path is verified
manually or via a separate integration test.

Checks:

  [A] Rule #1: budget exhausted → ESCALATE
  [B] Rule #2: max supervisor iterations → ESCALATE
  [C] Rule #3: stall detection (3 consecutive zero-completion) → ESCALATE
  [D] Rule #4: approved tasks remaining → WAIT
  [E] Rule #5: proposed + autonomous → ADVANCE_APPROVED
  [F] Rule #6: proposed + ai_assisted → ADVANCE_APPROVED
  [G] Rule #7: proposed + interactive → ESCALATE
  [H] Rule #8 stub: plan exhausted + outcomes → ESCALATE (Haiku not called in test)
  [I] Fallthrough: no branch matches → ESCALATE
  [J] Budget headroom breaker: insufficient headroom → ESCALATE
  [K] Idempotency: second call returns cached decision
  [L] Gate mode interaction: interactive never auto-advances
  [M] Event types: SupervisorDecisionEmittedEvent registered
  [N] Schema: execution_records has completed_task_count + failed_task_count
  [O] Schema: mission_plans has supervisor_iteration_count + max_supervisor_iterations

Usage:
    conda run -n mission-control python scripts/verify_autonomy_loop.py [-v]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
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


class AutonomyLoopVerifier:
    """Runs the Plan 51 Phase F acceptance suite."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._run_tag = uuid.uuid4().hex[:8]
        self._mission_id: str | None = None
        # Track created execution_record + decision IDs for cleanup.
        self._created_er_ids: list[str] = []
        self._created_decision_ids: list[str] = []

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    {msg}")

    def _pass(self, check: str) -> None:
        print(f"  {PASS} {check}")

    def _fail(self, check: str, detail: str) -> None:
        print(f"  {FAIL} {check}: {detail}")
        self._failures.append(f"{check}: {detail}")

    def _build_context(
        self,
        *,
        gate_mode: str = "autonomous",
        total_cost: float = 1.0,
        budget: float = 100.0,
        approved: int = 0,
        proposed: int = 0,
        recent_outcomes: list[dict] | None = None,
        supervisor_iterations: int = 0,
        max_iterations: int = 20,
        execution_record_id: str | None = None,
    ):
        """Build a synthetic GateContext for the reviewer."""
        from modules.backend.agents.mission_control.gate_models import GateContext

        return GateContext(
            gate_type="post_run",
            mission_id=self._mission_id or "test-mission",
            total_cost_usd=total_cost,
            budget_usd=budget,
            recent_run_outcomes=recent_outcomes or [],
            plan_task_summary={
                "approved": approved,
                "proposed": proposed,
                "running": 0,
                "completed": 5,
                "failed": 0,
                "total_completed": 5,
                "execution_record_id": execution_record_id,
                "max_supervisor_iterations": max_iterations,
            },
            mission_brief="Test mission brief",
            supervisor_iteration_count=supervisor_iterations,
        )

    async def _make_reviewer(self, gate_mode: str = "autonomous"):
        """Create a reviewer with a real db session (for idempotency tests)."""
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer
        from modules.backend.core.database import get_async_session

        session = get_async_session()
        db = await session.__aenter__()
        return (
            AutonomousPostRunReviewer(
                session=db,
                gate_mode=gate_mode,
            ),
            db,
            session,
        )

    async def setup(self) -> bool:
        """Find a host mission."""
        from sqlalchemy import select

        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission import Mission

        async with get_async_session() as db:
            result = await db.execute(select(Mission).limit(1))
            mission = result.scalar_one_or_none()
            if mission is None:
                print(f"\n{FAIL} Setup: no missions in DB.")
                return False
            self._mission_id = mission.id
            self._log(f"Using mission: {mission.id}")
        return True

    async def teardown(self) -> None:
        """Clean up created rows."""
        from sqlalchemy import delete

        from modules.backend.core.database import get_async_session
        from modules.backend.models.execution_record import ExecutionDecision, ExecutionRecord

        async with get_async_session() as db:
            if self._created_decision_ids:
                await db.execute(
                    delete(ExecutionDecision).where(
                        ExecutionDecision.id.in_(self._created_decision_ids)
                    )
                )
            if self._created_er_ids:
                await db.execute(
                    delete(ExecutionRecord).where(ExecutionRecord.id.in_(self._created_er_ids))
                )
            await db.commit()
        self._log(
            f"Cleaned up {len(self._created_er_ids)} ERs + {len(self._created_decision_ids)} decisions"  # noqa: E501
        )

    # ── Checks ───────────────────────────────────────────────────────

    async def check_rule_1_budget_exhausted(self) -> None:
        """[A] Budget exhausted → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(total_cost=100.0, budget=100.0)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Rule #1 budget exhausted", f"got {decision.action.value}")
            return
        self._pass("Rule #1: budget exhausted → ESCALATE")

    async def check_rule_2_max_iterations(self) -> None:
        """[B] Max supervisor iterations → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(supervisor_iterations=20, max_iterations=20)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Rule #2 max iterations", f"got {decision.action.value}")
            return
        self._pass("Rule #2: max supervisor iterations → ESCALATE")

    async def check_rule_3_stall(self) -> None:
        """[C] Stall detection → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        stall_outcomes = [
            {"completed_task_count": 0, "status": "failed"},
            {"completed_task_count": 0, "status": "failed"},
            {"completed_task_count": 0, "status": "failed"},
        ]
        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(recent_outcomes=stall_outcomes)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Rule #3 stall", f"got {decision.action.value}")
            return
        self._pass("Rule #3: 3 consecutive zero-completion waves → ESCALATE")

    async def check_rule_4_approved_remaining(self) -> None:
        """[D] Approved tasks remaining → WAIT."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(approved=3)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.WAIT:
            self._fail("Rule #4 approved remaining", f"got {decision.action.value}")
            return
        self._pass("Rule #4: approved tasks remaining → WAIT")

    async def check_rule_5_proposed_autonomous(self) -> None:
        """[E] Proposed + autonomous → ADVANCE_APPROVED."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(proposed=3)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ADVANCE_APPROVED:
            self._fail("Rule #5 proposed+autonomous", f"got {decision.action.value}")
            return
        self._pass("Rule #5: proposed + autonomous → ADVANCE_APPROVED")

    async def check_rule_6_proposed_ai_assisted(self) -> None:
        """[F] Proposed + ai_assisted → ADVANCE_APPROVED."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="ai_assisted")
        ctx = self._build_context(proposed=2)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ADVANCE_APPROVED:
            self._fail("Rule #6 proposed+ai_assisted", f"got {decision.action.value}")
            return
        self._pass("Rule #6: proposed + ai_assisted → ADVANCE_APPROVED")

    async def check_rule_7_proposed_interactive(self) -> None:
        """[G] Proposed + interactive → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="interactive")
        ctx = self._build_context(proposed=2)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Rule #7 proposed+interactive", f"got {decision.action.value}")
            return
        self._pass("Rule #7: proposed + interactive → ESCALATE")

    async def check_rule_8_plan_exhausted(self) -> None:
        """[H] Plan exhausted + outcomes → Haiku (stubs as ESCALATE without API)."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        # No proposed, no approved, but outcomes exist. Without a real
        # Haiku API key, the Haiku call fails and falls through to
        # ESCALATE. That's the expected behavior for this test.
        outcomes = [{"completed_task_count": 3, "status": "completed"}]
        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(recent_outcomes=outcomes)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            # If a real API key is configured, Haiku may return
            # ADVANCE_REFINE or PROPOSE_COMPLETE — both are valid.
            if decision.action in (GateAction.ADVANCE_REFINE, GateAction.PROPOSE_COMPLETE):
                self._pass("Rule #8: plan exhausted → Haiku classified (real API key)")
                return
            self._fail("Rule #8 plan exhausted", f"got {decision.action.value}")
            return
        self._pass("Rule #8: plan exhausted → ESCALATE (Haiku stub/failure fallthrough)")

    async def check_fallthrough(self) -> None:
        """[I] No branch matches → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        # No proposed, no approved, no outcomes → no rule matches.
        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(recent_outcomes=[])
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Fallthrough", f"got {decision.action.value}")
            return
        self._pass("Fallthrough: no branch matches → ESCALATE")

    async def check_budget_headroom(self) -> None:
        """[J] Budget headroom insufficient → ESCALATE."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        # Budget almost gone, proposed tasks would exceed headroom.
        # avg_cost = 99/5 = 19.8 per task. 3 proposed * 19.8 * 1.5 = 89.1.
        # Remaining = 100 - 99 = 1.0. 1.0 < 89.1 → ESCALATE.
        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="autonomous")
        ctx = self._build_context(total_cost=99.0, budget=100.0, proposed=3)
        decision = await reviewer.review(ctx)
        if decision.action != GateAction.ESCALATE:
            self._fail("Budget headroom", f"got {decision.action.value}")
            return
        self._pass("Budget headroom: insufficient → ESCALATE")

    async def check_idempotency(self) -> None:
        """[K] Second reviewer call returns cached decision from audit trail."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.core.database import get_async_session
        from modules.backend.models.execution_record import ExecutionDecision, ExecutionRecord

        # Create a real execution_record + decision row, then call
        # the reviewer with that execution_record_id and verify it
        # returns the cached decision.
        er_id = str(uuid.uuid4())

        async with get_async_session() as db:
            er = ExecutionRecord(
                id=er_id,
                session_id=str(uuid.uuid4()),
                mission_id=self._mission_id,
                status="completed",
            )
            db.add(er)
            await db.flush()
            self._created_er_ids.append(er_id)

            # Write a cached decision.
            import json

            meta = json.dumps(
                {
                    "action": "wait",
                    "reviewer": "config:rule_engine",
                    "rule": 4,
                    "model_metadata": None,
                }
            )
            dec = ExecutionDecision(
                execution_record_id=er_id,
                decision_type="post_run_supervisor",
                reasoning=f"3 approved tasks remaining.\n{meta}",
            )
            db.add(dec)
            await db.flush()
            self._created_decision_ids.append(dec.id)
            await db.commit()

        # Now call the reviewer — it should find the cached row.
        async with get_async_session() as db:
            from modules.backend.agents.mission_control.gate_post_run import (
                AutonomousPostRunReviewer,
            )

            reviewer = AutonomousPostRunReviewer(session=db, gate_mode="autonomous")
            ctx = self._build_context(
                # These values would normally trigger rule #5
                # (proposed + autonomous → ADVANCE_APPROVED), but
                # the cached decision says WAIT.
                proposed=5,
                execution_record_id=er_id,
            )
            decision = await reviewer.review(ctx)

        if decision.action != GateAction.WAIT:
            self._fail(
                "Idempotency",
                f"expected WAIT (cached), got {decision.action.value}",
            )
            return
        self._pass("Idempotency: second call returns cached WAIT despite proposed=5")

    async def check_gate_mode_interactive(self) -> None:
        """[L] Interactive mode never auto-advances even with proposed tasks."""
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer

        # Same context that would ADVANCE_APPROVED in autonomous mode,
        # but interactive → ESCALATE.
        reviewer = AutonomousPostRunReviewer(session=None, gate_mode="interactive")
        ctx = self._build_context(proposed=5)
        decision = await reviewer.review(ctx)
        if decision.action == GateAction.ADVANCE_APPROVED:
            self._fail("Interactive guard", "auto-advanced in interactive mode!")
            return
        if decision.action != GateAction.ESCALATE:
            self._fail("Interactive guard", f"expected ESCALATE, got {decision.action.value}")
            return
        self._pass("Gate mode: interactive never auto-advances")

    async def check_event_types_registered(self) -> None:
        """[M] Event types registered in EVENT_TYPE_MAP."""
        from modules.backend.events.types import EVENT_TYPE_MAP

        missing = []
        for evt in [
            "mission_plan.supervisor_decision",
            "session.followup.fired",
        ]:
            if evt not in EVENT_TYPE_MAP:
                missing.append(evt)
        if missing:
            self._fail("Event types registered", f"missing: {missing}")
            return
        self._pass("Event types: supervisor_decision + followup.fired registered")

    async def check_schema_execution_records(self) -> None:
        """[N] execution_records has completed_task_count + failed_task_count columns."""
        from sqlalchemy import inspect as sa_inspect

        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            bind = await db.connection()
            raw = await bind.run_sync(
                lambda conn: {c["name"] for c in sa_inspect(conn).get_columns("execution_records")}
            )

        needed = {"completed_task_count", "failed_task_count"}
        missing = needed - raw
        if missing:
            self._fail("execution_records columns", f"missing: {missing}")
            return
        self._pass("Schema: execution_records has completed_task_count + failed_task_count")

    async def check_schema_mission_plans(self) -> None:
        """[O] mission_plans has supervisor counters."""
        from sqlalchemy import inspect as sa_inspect

        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            bind = await db.connection()
            raw = await bind.run_sync(
                lambda conn: {c["name"] for c in sa_inspect(conn).get_columns("mission_plans")}
            )

        needed = {"supervisor_iteration_count", "max_supervisor_iterations"}
        missing = needed - raw
        if missing:
            self._fail("mission_plans columns", f"missing: {missing}")
            return
        self._pass(
            "Schema: mission_plans has supervisor_iteration_count + max_supervisor_iterations"
        )

    # ── Runner ───────────────────────────────────────────────────────

    async def run(self) -> bool:
        print(f"\nPlan 51 Phase F — Autonomy Loop Verification " f"(run_tag={self._run_tag})")
        print("=" * 70)

        print("\n[Setup]")
        if not await self.setup():
            return False

        print("\n[A-C] Circuit breakers")
        await self.check_rule_1_budget_exhausted()
        await self.check_rule_2_max_iterations()
        await self.check_rule_3_stall()

        print("\n[D] Approved remaining")
        await self.check_rule_4_approved_remaining()

        print("\n[E-G] Proposed + gate_mode variants")
        await self.check_rule_5_proposed_autonomous()
        await self.check_rule_6_proposed_ai_assisted()
        await self.check_rule_7_proposed_interactive()

        print("\n[H] Plan exhausted (Haiku stub)")
        await self.check_rule_8_plan_exhausted()

        print("\n[I] Fallthrough")
        await self.check_fallthrough()

        print("\n[J] Budget headroom")
        await self.check_budget_headroom()

        print("\n[K] Idempotency")
        await self.check_idempotency()

        print("\n[L] Gate mode interaction")
        await self.check_gate_mode_interactive()

        print("\n[M] Event types")
        await self.check_event_types_registered()

        print("\n[N-O] Schema columns")
        await self.check_schema_execution_records()
        await self.check_schema_mission_plans()

        print("\n" + "=" * 70)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        print("PASSED — all autonomy loop checks passed (15/15)")
        return True


async def _main(verbose: bool) -> int:
    verifier = AutonomyLoopVerifier(verbose=verbose)
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
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show debug details for each check",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.verbose)))


if __name__ == "__main__":
    main()
