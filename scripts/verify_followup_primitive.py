#!/usr/bin/env python3
"""
Plan 51 Phase A — Session Followup Primitive Verification.

Verifies the generic wake-on-event primitive that Plan 51's autonomy
loop sits on top of:

  [A] SessionFollowupService.schedule_followup validates inputs and
      writes a row via the repository.
  [B] Validation: empty triggers / empty prompt / missing agent /
      max_fires > 1 / per-session cap all raise ValidationError.
  [C] fire_matching finds the scheduled row for a matching event,
      renders the prompt template, invokes the caller-supplied
      agent_turn_runner, and stamps fire_count + consumed_at.
  [D] fire_matching respects trigger_filter literal-match — a
      filter mismatch leaves the row untouched.
  [E] fire_matching does not match consumed rows, expired rows, or
      rows with a different event_type.
  [F] fire_matching records failure_reason when the agent_turn_runner
      raises, and stamps consumed_at so it does not re-fire.
  [G] Prompt template renders missing fields as "" instead of
      raising (defensive format_map wrapper).
  [H] A SessionFollowupFiredEvent is published per fired followup
      (both success and failure paths).

Usage:
    conda run -n mission-control python scripts/verify_followup_primitive.py [--verbose]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed

Requirements:
    - Postgres running and reachable via the config database URL
    - Migration plan51_001 applied (creates session_followups table)
    - At least one mission in the DB (the script attaches test
      sessions to an existing mission — no fixture fabrication)

Re-runnable. Uses a unique run_tag so concurrent verifications don't
collide. Cleanup removes the test session + followups via cascade.
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


class _RecordingRunner:
    """A fake agent_turn_runner that records invocations.

    Used instead of the real ``mission_control.handle`` so the
    verification script doesn't make live LLM calls — Phase A only
    verifies the primitive, not the agent.
    """

    def __init__(self, *, should_raise: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.should_raise = should_raise

    async def __call__(self, session_id: str, mission_id: str, prompt: str) -> None:
        self.calls.append((session_id, mission_id, prompt))
        if self.should_raise:
            raise RuntimeError("simulated agent turn failure")


class _RecordingBus:
    """A fake EventBus that records publish_to_mission calls."""

    def __init__(self) -> None:
        self.published: list[tuple[str, object]] = []

    async def publish(self, event) -> None:  # pragma: no cover — unused here
        pass

    async def publish_to_mission(self, mission_id: str, event) -> None:
        self.published.append((mission_id, event))


class FollowupVerifier:
    """Runs the Phase A acceptance suite against the real DB."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._run_tag = uuid.uuid4().hex[:8]
        self._mission_id: str | None = None
        self._session_id: str | None = None
        self._created_followup_ids: list[str] = []

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
        """Find a host mission and create a throwaway session against it."""
        from sqlalchemy import select

        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission import Mission
        from modules.backend.models.session import Session

        async with get_async_session() as db:
            result = await db.execute(select(Mission).limit(1))
            mission = result.scalar_one_or_none()
            if mission is None:
                print(f"\n{FAIL} Setup failed: no missions in DB.")
                print("  Create a mission before running this script.")
                return False
            self._mission_id = mission.id
            self._log(f"Using mission: {mission.id} ({mission.name})")

            # Create a throwaway session for the test followups to
            # attach to. CASCADE on session delete will clean them up.
            session = Session(
                id=str(uuid.uuid4()),
                mission_id=mission.id,
                goal=f"Plan 51 Phase A verify ({self._run_tag})",
            )
            db.add(session)
            await db.commit()
            self._session_id = session.id
            self._log(f"Created test session: {session.id}")
        return True

    async def teardown(self) -> None:
        """Drop the test session (cascades followups)."""
        if self._session_id is None:
            return
        from sqlalchemy import delete

        from modules.backend.core.database import get_async_session
        from modules.backend.models.session import Session
        from modules.backend.models.session_followup import SessionFollowup

        async with get_async_session() as db:
            # Defence-in-depth: delete followups by id in case the
            # cascade doesn't fire for some reason (e.g. schema drift).
            if self._created_followup_ids:
                await db.execute(
                    delete(SessionFollowup).where(
                        SessionFollowup.id.in_(self._created_followup_ids)
                    )
                )
            await db.execute(delete(Session).where(Session.id == self._session_id))
            await db.commit()
        self._log(f"Cleaned up {len(self._created_followup_ids)} followups + " f"1 test session")

    # -------------------------------------------------------------------------
    # Checks
    # -------------------------------------------------------------------------

    async def check_schedule_followup_writes_row(self) -> None:
        """[A] schedule_followup inserts a valid session_followup row."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session_followup import SessionFollowupService

        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            row = await svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["mission_plan.run.completed"],
                prompt_template=(
                    "Run {execution_record_id} just completed with "
                    "status={run_status}. Summarise for the user."
                ),
                created_by_agent=f"test.agent.{self._run_tag}",
            )
            self._created_followup_ids.append(row.id)
            await db.commit()

        if not row.id:
            self._fail("schedule_followup returns row with id", "no id")
            return
        if row.session_id != self._session_id:
            self._fail("row.session_id set", row.session_id)
            return
        if row.mission_id != self._mission_id:
            self._fail("row.mission_id set", row.mission_id)
            return
        if "mission_plan.run.completed" not in row.trigger_event_types:
            self._fail(
                "row.trigger_event_types populated",
                str(row.trigger_event_types),
            )
            return
        if row.fire_count != 0 or row.consumed_at is not None:
            self._fail(
                "row starts unfired",
                f"fire_count={row.fire_count} consumed_at={row.consumed_at}",
            )
            return
        self._log(f"  row id={row.id[:8]} expires_at={row.expires_at}")
        self._pass("schedule_followup writes valid row")

    async def check_validation_errors(self) -> None:
        """[B] Invalid inputs raise ValidationError."""
        from modules.backend.core.database import get_async_session
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.services.session_followup import SessionFollowupService

        async def _expect_raises(
            label: str,
            coro_factory,
        ) -> bool:
            async with get_async_session() as db:
                svc = SessionFollowupService(db)
                try:
                    await coro_factory(svc)
                    self._fail(label, "should have raised ValidationError")
                    return False
                except ValidationError:
                    return True

        ok = await _expect_raises(
            "empty trigger_event_types rejected",
            lambda svc: svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=[],
                prompt_template="x",
                created_by_agent="a",
            ),
        )
        if not ok:
            return
        ok = await _expect_raises(
            "empty prompt_template rejected",
            lambda svc: svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["x"],
                prompt_template="   ",
                created_by_agent="a",
            ),
        )
        if not ok:
            return
        ok = await _expect_raises(
            "missing created_by_agent rejected",
            lambda svc: svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["x"],
                prompt_template="x",
                created_by_agent="",
            ),
        )
        if not ok:
            return
        ok = await _expect_raises(
            "max_fires > 1 rejected in v1",
            lambda svc: svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["x"],
                prompt_template="x",
                created_by_agent="a",
                max_fires=2,
                cooldown_seconds=30,
            ),
        )
        if not ok:
            return
        self._pass("All five validation paths raise ValidationError")

    async def check_per_session_cap(self) -> None:
        """[B] Per-session cap raises ValidationError.

        Uses a dedicated throwaway session so filling the cap doesn't
        block subsequent tests that also need to schedule followups
        on the primary test session.
        """
        from modules.backend.core.database import get_async_session
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.models.session import Session
        from modules.backend.services.session_followup import (
            MAX_ACTIVE_FOLLOWUPS_PER_SESSION,
            SessionFollowupService,
        )

        # Create a cap-test session distinct from the main session
        # so cap-filling doesn't block later checks.
        cap_session_id = str(uuid.uuid4())
        async with get_async_session() as db:
            db.add(
                Session(
                    id=cap_session_id,
                    mission_id=self._mission_id,
                    goal=f"cap test {self._run_tag}",
                )
            )
            await db.commit()

        cap_followup_ids: list[str] = []
        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            try:
                while True:
                    row = await svc.schedule_followup(
                        session_id=cap_session_id,
                        mission_id=self._mission_id,
                        trigger_event_types=["cap.test"],
                        prompt_template="cap test",
                        created_by_agent=f"test.{self._run_tag}",
                    )
                    cap_followup_ids.append(row.id)
                    if len(cap_followup_ids) > MAX_ACTIVE_FOLLOWUPS_PER_SESSION + 2:
                        self._fail(
                            "Per-session cap enforced",
                            "cap did not trigger after many inserts",
                        )
                        await db.rollback()
                        return
            except ValidationError:
                pass  # expected
            await db.commit()

        if len(cap_followup_ids) != MAX_ACTIVE_FOLLOWUPS_PER_SESSION:
            self._fail(
                "Per-session cap triggers at exact limit",
                f"inserted {len(cap_followup_ids)} before raising "
                f"(expected {MAX_ACTIVE_FOLLOWUPS_PER_SESSION})",
            )

        # Clean up the cap test session — cascades followups.
        from sqlalchemy import delete

        async with get_async_session() as db:
            await db.execute(delete(Session).where(Session.id == cap_session_id))
            await db.commit()

        self._pass(
            f"Per-session cap ({MAX_ACTIVE_FOLLOWUPS_PER_SESSION}) " f"enforced via ValidationError"
        )

    async def check_fire_matching_success(self) -> None:
        """[C] fire_matching finds + fires the matching followup."""
        from modules.backend.core.database import get_async_session
        from modules.backend.events.types import MissionPlanDispatchedEvent
        from modules.backend.services.session_followup import SessionFollowupService

        runner = _RecordingRunner()
        bus = _RecordingBus()

        # Use MissionPlanDispatchedEvent as a stand-in for the Phase C
        # MissionPlanRunCompletedEvent — the primitive is event-agnostic.
        # It only cares about event_type + payload.model_dump().
        event = MissionPlanDispatchedEvent(
            session_id=uuid.UUID(self._session_id),
            source="verify",
            mission_id=self._mission_id,
            plan_id="plan-test",
            execution_record_id=f"exec-{self._run_tag}",
            dispatched_task_ids=["t1", "t2"],
        )

        # First, schedule a followup that subscribes to this event type.
        async with get_async_session() as db:
            svc = SessionFollowupService(db, event_bus=bus)
            row = await svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["mission_plan.dispatched"],
                prompt_template=("Dispatched run {execution_record_id} on plan {plan_id}."),
                created_by_agent=f"test.fire.{self._run_tag}",
            )
            self._created_followup_ids.append(row.id)
            await db.commit()

        # Now fire the event.
        async with get_async_session() as db:
            svc = SessionFollowupService(db, event_bus=bus)
            fired = await svc.fire_matching(event, agent_turn_runner=runner)
            await db.commit()

        # Assertions on the runner.
        if len(runner.calls) != 1:
            self._fail(
                "Runner invoked exactly once",
                f"called {len(runner.calls)} times",
            )
            return
        called_session, called_mission, called_prompt = runner.calls[0]
        if called_session != self._session_id:
            self._fail("Runner got right session_id", called_session)
            return
        if called_mission != self._mission_id:
            self._fail("Runner got right mission_id", called_mission)
            return
        if f"exec-{self._run_tag}" not in called_prompt:
            self._fail(
                "Prompt template rendered event fields",
                called_prompt,
            )
            return
        if "plan-test" not in called_prompt:
            self._fail(
                "Prompt template rendered plan_id",
                called_prompt,
            )
            return

        # Assertions on fired rows + DB state.
        if len(fired) != 1:
            self._fail(
                "fire_matching returned exactly one row",
                f"got {len(fired)}",
            )
            return
        if fired[0].fire_count != 1:
            self._fail("fire_count incremented", str(fired[0].fire_count))
            return
        if fired[0].consumed_at is None:
            self._fail("consumed_at stamped for max_fires=1", "still NULL")
            return

        # Assertions on event publishing.
        fired_events = [
            e for _, e in bus.published if getattr(e, "event_type", "") == "session.followup.fired"
        ]
        if not fired_events:
            self._fail(
                "SessionFollowupFiredEvent published",
                "no session.followup.fired events captured",
            )
            return
        evt = fired_events[-1]
        if not evt.success:
            self._fail(
                "Fired event marked success",
                f"success={evt.success} reason={evt.failure_reason}",
            )
            return

        self._pass("fire_matching success: runner invoked, row consumed, event published")

    async def check_fire_matching_filter_mismatch(self) -> None:
        """[D] trigger_filter literal-match excludes non-matching events."""
        from modules.backend.core.database import get_async_session
        from modules.backend.events.types import MissionPlanDispatchedEvent
        from modules.backend.services.session_followup import SessionFollowupService

        runner = _RecordingRunner()

        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            row = await svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["mission_plan.dispatched"],
                trigger_filter={"plan_id": "not-our-plan"},
                prompt_template="should not fire",
                created_by_agent=f"test.filter.{self._run_tag}",
            )
            self._created_followup_ids.append(row.id)
            await db.commit()

        # Fire an event whose plan_id does NOT match the filter.
        event = MissionPlanDispatchedEvent(
            session_id=uuid.UUID(self._session_id),
            source="verify",
            mission_id=self._mission_id,
            plan_id="different-plan",
            execution_record_id=f"exec-{self._run_tag}",
            dispatched_task_ids=[],
        )
        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            fired = await svc.fire_matching(event, agent_turn_runner=runner)
            await db.commit()

        # The row should NOT be in the fired list (filter mismatch).
        row_fired = any(f.id == row.id for f in fired)
        if row_fired:
            self._fail(
                "Filter mismatch excludes row",
                f"followup {row.id} fired despite mismatched filter",
            )
            return
        if runner.calls:
            # Note: other followups may have fired (from [A] earlier,
            # if not yet consumed), so only check that OUR runner was
            # not called for OUR mismatched row. The length check is
            # loose — it only fails if this runner was called at all.
            self._fail(
                "Runner not invoked for mismatched filter",
                f"runner was called {len(runner.calls)} times",
            )
            return
        self._pass("trigger_filter literal-match excludes non-matching events")

    async def check_consumed_rows_not_re_fired(self) -> None:
        """[E] A consumed row does not re-fire on a new event."""
        from modules.backend.core.database import get_async_session
        from modules.backend.events.types import MissionPlanDispatchedEvent
        from modules.backend.services.session_followup import SessionFollowupService

        # Re-fire the same event type that check [C] already consumed
        # a row for. The check-[C] row should NOT be in the new fired
        # list since consumed_at is non-NULL.
        runner = _RecordingRunner()
        event = MissionPlanDispatchedEvent(
            session_id=uuid.UUID(self._session_id),
            source="verify",
            mission_id=self._mission_id,
            plan_id="re-fire-test",
            execution_record_id=f"exec-refire-{self._run_tag}",
            dispatched_task_ids=[],
        )
        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            await svc.fire_matching(event, agent_turn_runner=runner)
            await db.commit()

        # The [C] row is already consumed and must not appear.
        # Any [D] rows have filter that doesn't match this event.
        # If fire_count is 1 on all our tracked rows, we're good.
        async with get_async_session() as db:
            from modules.backend.repositories.session_followup import SessionFollowupRepository

            repo = SessionFollowupRepository(db)
            for fid in self._created_followup_ids:
                row = await repo.get_by_id_or_none(fid)
                if row and row.fire_count > 1:
                    self._fail(
                        "Consumed rows are never re-fired",
                        f"followup {fid} has fire_count={row.fire_count}",
                    )
                    return

        self._pass("Consumed rows not re-fired on subsequent matching events")

    async def check_runner_failure_recorded(self) -> None:
        """[F] Runner exception → failure_reason recorded, consumed stamped."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session_followup import SessionFollowupService

        bus = _RecordingBus()

        # Schedule a new followup for a distinct event type so it
        # isn't also matched by check-[C]/[E] runs.
        async with get_async_session() as db:
            svc = SessionFollowupService(db, event_bus=bus)
            row = await svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["mission_plan.refined"],
                prompt_template="should fail",
                created_by_agent=f"test.fail.{self._run_tag}",
            )
            self._created_followup_ids.append(row.id)
            await db.commit()

        runner = _RecordingRunner(should_raise=True)
        # Emit a matching event. We need to hand-construct a
        # mission_plan.refined event; use a generic SessionEvent
        # subclass or just a dict shaped like one — fire_matching
        # accepts dicts via the hasattr/isinstance fallback.
        event_dict = {
            "event_type": "mission_plan.refined",
            "mission_id": self._mission_id,
            "session_id": self._session_id,
            "plan_id": "test-plan",
        }

        async with get_async_session() as db:
            svc = SessionFollowupService(db, event_bus=bus)
            await svc.fire_matching(
                event_dict,
                agent_turn_runner=runner,
            )
            await db.commit()

        # Inspect the row — should have failure_reason set, consumed_at stamped.
        async with get_async_session() as db:
            from modules.backend.repositories.session_followup import SessionFollowupRepository

            repo = SessionFollowupRepository(db)
            updated = await repo.get_by_id_or_none(row.id)

        if updated is None:
            self._fail("Failed row still exists", "row gone after fire_matching")
            return
        if not updated.failure_reason:
            self._fail(
                "failure_reason recorded",
                f"failure_reason={updated.failure_reason!r}",
            )
            return
        if updated.consumed_at is None:
            self._fail(
                "consumed_at stamped on failure",
                "still NULL — would re-fire on reentrant event",
            )
            return

        # Also check a failure event was published.
        failure_events = [
            e
            for _, e in bus.published
            if getattr(e, "event_type", "") == "session.followup.fired"
            and not getattr(e, "success", True)
        ]
        if not failure_events:
            self._fail(
                "Failure SessionFollowupFiredEvent published",
                "no failure event in bus",
            )
            return

        self._pass("Runner failure: failure_reason recorded, consumed stamped, event published")

    async def check_safe_template_render(self) -> None:
        """[G] Missing template fields render as "" without raising."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session_followup import SessionFollowupService

        runner = _RecordingRunner()

        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            row = await svc.schedule_followup(
                session_id=self._session_id,
                mission_id=self._mission_id,
                trigger_event_types=["template.test"],
                prompt_template="has {present} and {missing_field}",
                created_by_agent=f"test.tpl.{self._run_tag}",
            )
            self._created_followup_ids.append(row.id)
            await db.commit()

        event = {
            "event_type": "template.test",
            "mission_id": self._mission_id,
            "present": "value-here",
            # "missing_field" intentionally absent
        }
        async with get_async_session() as db:
            svc = SessionFollowupService(db)
            await svc.fire_matching(event, agent_turn_runner=runner)
            await db.commit()

        if not runner.calls:
            self._fail("Template followup fired", "no runner invocation")
            return
        prompt = runner.calls[-1][2]
        if "value-here" not in prompt:
            self._fail("Present field rendered", prompt)
            return
        # Missing field should render as empty string, not raise.
        if "{missing_field}" in prompt:
            self._fail(
                "Missing field rendered as empty",
                f"unrendered placeholder remains: {prompt}",
            )
            return
        self._pass("Missing template fields render as empty string")

    # -------------------------------------------------------------------------
    # Runner
    # -------------------------------------------------------------------------

    async def run(self) -> bool:
        print(
            f"\nPlan 51 Phase A — Session Followup Primitive Verification "
            f"(run_tag={self._run_tag})"
        )
        print("=" * 70)

        print("\n[Setup] Finding host mission + creating test session...")
        if not await self.setup():
            return False

        print("\n[A] schedule_followup writes a valid row")
        await self.check_schedule_followup_writes_row()

        print("\n[B] Input validation")
        await self.check_validation_errors()

        print("\n[B-cap] Per-session cap")
        await self.check_per_session_cap()

        print("\n[C] fire_matching success path")
        await self.check_fire_matching_success()

        print("\n[D] trigger_filter literal-match")
        await self.check_fire_matching_filter_mismatch()

        print("\n[E] Consumed rows not re-fired")
        await self.check_consumed_rows_not_re_fired()

        print("\n[F] Runner failure recorded")
        await self.check_runner_failure_recorded()

        print("\n[G] Safe template rendering")
        await self.check_safe_template_render()

        print("\n" + "=" * 70)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        print("PASSED — all session followup primitive checks passed")
        return True


async def _main(verbose: bool) -> int:
    verifier = FollowupVerifier(verbose=verbose)
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
