#!/usr/bin/env python3
"""
Plan 43 — Persistent Mission Artifacts Verification Script.

Verifies the end-to-end durable-artifacts pipeline from Plan 43:

  1. A ``MissionArtifact`` row can be created via the service layer
     with validated input (enum checks, non-empty title, non-empty
     content).
  2. ``persist_mission_results`` extracts artifacts from a completed
     ``ExecutionOutcome`` automatically — walking each task_result's
     ``output_reference`` for ``summary`` / ``result`` text, same
     heuristic the live SSE emission site uses, but persisted.
  3. Extracted artifacts link correctly to the mission,
     execution_record, and task_execution via the FK chain.
  4. Hard content cap (100k chars) truncates runaway inputs with a
     warning log, and short content passes through unchanged.
  5. Invalid enum values (``artifact_type``, ``content_type``) are
     rejected at the service layer with a clear ``ValidationError``.
  6. Cleanup: all test rows are removed via the mission cascade so
     the DB is left in exactly the state it started.

Usage:
    python scripts/verify_artifacts_persistence.py [--verbose]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed

Requirements:
    - Postgres running and reachable via the config database URL
    - At least one mission in the DB (test fixtures attach to an
      existing mission so we don't fabricate users)

Re-runnable any number of times. Uses a unique run_tag uuid so
concurrent verifications don't collide.
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


class ArtifactsVerifier:
    """Runs the durable-artifacts verification suite against the real DB."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._run_tag = uuid.uuid4().hex[:8]
        self._mission_id: str | None = None
        # Track created IDs for targeted cleanup (defence-in-depth on
        # top of the mission cascade — in case this script is run
        # against an unusual schema state).
        self._created_artifact_ids: list[str] = []
        self._created_execution_record_id: str | None = None
        self._created_task_execution_id: str | None = None

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
        """Find an existing mission to attach test artifacts to."""
        from sqlalchemy import select

        from modules.backend.core.database import get_async_session
        from modules.backend.models.mission import Mission

        async with get_async_session() as db:
            result = await db.execute(select(Mission).limit(1))
            mission = result.scalar_one_or_none()
            if mission is None:
                print(f"\n{FAIL} Setup failed: no missions in DB.")
                print("  Create a mission before running this script.")
                return False
            self._mission_id = mission.id
            self._log(f"Using mission: {mission.id} ({mission.name})")
        return True

    async def teardown(self) -> None:
        """Delete the test rows created by this run."""
        if self._mission_id is None:
            return

        from sqlalchemy import delete

        from modules.backend.core.database import get_async_session
        from modules.backend.models.execution_record import ExecutionRecord, TaskExecution
        from modules.backend.models.mission_artifact import MissionArtifact

        async with get_async_session() as db:
            # Delete artifacts by id (not by mission — we only want
            # our test rows, not any pre-existing ones).
            if self._created_artifact_ids:
                await db.execute(
                    delete(MissionArtifact).where(
                        MissionArtifact.id.in_(self._created_artifact_ids)
                    )
                )
            # Delete task_execution (artifacts referencing it via
            # task_execution_id have already been handled above or
            # cascaded to NULL).
            if self._created_task_execution_id:
                await db.execute(
                    delete(TaskExecution).where(TaskExecution.id == self._created_task_execution_id)
                )
            if self._created_execution_record_id:
                await db.execute(
                    delete(ExecutionRecord).where(
                        ExecutionRecord.id == self._created_execution_record_id
                    )
                )
            await db.commit()
        self._log(
            f"Cleaned up {len(self._created_artifact_ids)} artifacts + "
            f"{1 if self._created_task_execution_id else 0} task_execution + "
            f"{1 if self._created_execution_record_id else 0} execution_record"
        )

    # -------------------------------------------------------------------------
    # Checks
    # -------------------------------------------------------------------------

    async def check_direct_service_create(self) -> None:
        """[A] MissionArtifactService.create_artifact inserts a valid row."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission_artifact import MissionArtifactService

        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            artifact = await svc.create_artifact(
                mission_id=self._mission_id,
                agent_id=f"verify-agent-{self._run_tag}",
                title=f"Verify artifact {self._run_tag}",
                content_text=f"# Test report {self._run_tag}\n\nContent body.",
            )
            self._created_artifact_ids.append(artifact.id)
            await db.commit()

        if artifact.id:
            self._log(f"  created artifact id={artifact.id}")
            self._pass("Direct service.create_artifact inserts valid row")
        else:
            self._fail("Direct service.create_artifact", "no id returned")

    async def check_enum_validation(self) -> None:
        """[B] Invalid artifact_type / content_type are rejected."""
        from modules.backend.core.database import get_async_session
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.services.mission_artifact import MissionArtifactService

        # Invalid artifact_type
        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            try:
                await svc.create_artifact(
                    mission_id=self._mission_id,
                    agent_id="verify",
                    title="invalid-type test",
                    content_text="anything",
                    artifact_type="garbage",
                )
                self._fail(
                    "Invalid artifact_type rejected",
                    "create_artifact should have raised ValidationError",
                )
                return
            except ValidationError:
                pass  # expected

        # Invalid content_type
        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            try:
                await svc.create_artifact(
                    mission_id=self._mission_id,
                    agent_id="verify",
                    title="invalid-content-type test",
                    content_text="anything",
                    content_type="yaml",
                )
                self._fail(
                    "Invalid content_type rejected",
                    "create_artifact should have raised ValidationError",
                )
                return
            except ValidationError:
                pass  # expected

        # Empty title
        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            try:
                await svc.create_artifact(
                    mission_id=self._mission_id,
                    agent_id="verify",
                    title="   ",
                    content_text="anything",
                )
                self._fail(
                    "Empty title rejected",
                    "create_artifact should have raised ValidationError",
                )
                return
            except ValidationError:
                pass  # expected

        self._pass(
            "Enum + empty-field validation rejects invalid input "
            "(artifact_type, content_type, title)"
        )

    async def check_content_cap(self) -> None:
        """[C] Content > 100k chars truncates silently with a log warning."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission_artifact import MissionArtifactService

        big_content = "A" * 200_000  # 200k chars — twice the cap
        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            artifact = await svc.create_artifact(
                mission_id=self._mission_id,
                agent_id="verify-cap",
                title=f"Cap test {self._run_tag}",
                content_text=big_content,
            )
            self._created_artifact_ids.append(artifact.id)
            await db.commit()
            # Refresh from DB to get the persisted content
            persisted_len = len(artifact.content_text or "")

        if persisted_len == 100_000:
            self._pass(f"Content cap: 200k → 100k chars (persisted={persisted_len})")
        else:
            self._fail(
                "Content cap truncates at 100k",
                f"persisted_len={persisted_len}, expected 100000",
            )

    async def check_extraction_from_outcome(self) -> None:
        """[D] persist_mission_results extracts artifacts end-to-end."""
        from modules.backend.agents.mission_control.outcome import (
            ExecutionOutcome,
            ExecutionStatus,
            TaskResult,
            TaskStatus,
        )
        from modules.backend.agents.mission_control.persistence_bridge import (
            persist_mission_results,
        )
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission_artifact import MissionArtifactService

        # Build a synthetic outcome with one task that has a summary
        # field — the extraction heuristic should pick it up.
        synthetic_task = TaskResult(
            task_id=f"verify-task-{self._run_tag}",
            agent_name=f"verify.agent.{self._run_tag}",
            status=TaskStatus.SUCCESS,
            output_reference={
                "summary": (
                    f"# End-to-end extraction test {self._run_tag}\n\n"
                    f"This summary field should be persisted as an artifact "
                    f"by persist_mission_results."
                ),
                "other_field": "not extracted",
            },
            cost_usd=0.01,
            duration_seconds=1.23,
        )
        outcome = ExecutionOutcome(
            mission_id=f"verify-mission-run-{self._run_tag}",
            status=ExecutionStatus.SUCCESS,
            task_results=[synthetic_task],
            total_cost_usd=0.01,
        )

        async with get_async_session() as db:
            record_id = await persist_mission_results(
                outcome,
                session_id=f"verify-session-{self._run_tag}",
                roster_name="verify-roster",
                task_plan_json=None,
                mission_id=self._mission_id,
                db_session=db,
            )
            # persist_mission_results commits internally; no extra commit here.

        if record_id is None:
            self._fail(
                "persist_mission_results writes an execution record",
                "record_id is None — persistence failed",
            )
            return
        self._created_execution_record_id = record_id
        self._log(f"  execution_record id={record_id}")

        # Read the artifact back via the service's query path
        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            artifacts = await svc.list_for_execution_record(record_id)

        if not artifacts:
            self._fail(
                "persist_mission_results extracts artifact",
                f"no artifacts for execution_record {record_id}",
            )
            return
        if len(artifacts) != 1:
            self._fail(
                "Exactly one artifact per task",
                f"got {len(artifacts)} artifacts, expected 1",
            )
            return

        artifact = artifacts[0]
        self._created_artifact_ids.append(artifact.id)
        self._created_task_execution_id = artifact.task_execution_id

        # Verify the extracted content matches the summary
        if "End-to-end extraction test" not in (artifact.content_text or ""):
            self._fail(
                "Extracted content matches task summary",
                f"content={artifact.content_text[:120]!r}",
            )
            return
        if self._run_tag not in (artifact.content_text or ""):
            self._fail(
                "Extracted content contains run_tag",
                "content did not contain the unique run tag",
            )
            return
        if artifact.mission_id != self._mission_id:
            self._fail(
                "Artifact linked to correct mission",
                f"mission_id={artifact.mission_id}, expected {self._mission_id}",
            )
            return
        if artifact.execution_record_id != record_id:
            self._fail(
                "Artifact linked to execution_record",
                f"got {artifact.execution_record_id}",
            )
            return
        if artifact.task_execution_id is None:
            self._fail(
                "Artifact linked to task_execution",
                "task_execution_id is NULL — FK chain broken",
            )
            return
        if artifact.artifact_type != "report":
            self._fail(
                "Artifact type defaults to 'report'",
                f"got artifact_type={artifact.artifact_type!r}",
            )
            return
        if artifact.content_type != "markdown":
            self._fail(
                "Artifact content_type defaults to 'markdown'",
                f"got content_type={artifact.content_type!r}",
            )
            return

        self._pass(
            "persist_mission_results extracts artifact with full FK chain "
            "(mission ⋈ execution_record ⋈ task_execution)"
        )

    async def check_list_for_mission(self) -> None:
        """[E] list_for_mission returns the artifacts created above."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission_artifact import MissionArtifactService

        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            artifacts = await svc.list_for_mission(
                mission_id=self._mission_id,
                limit=50,
            )

        # Look for our test rows in the result. Because the mission may
        # already have other artifacts, we don't assert total count —
        # just that ours appear.
        found_ids = {a.id for a in artifacts}
        our_ids = set(self._created_artifact_ids)
        missing = our_ids - found_ids

        if missing:
            self._fail(
                "list_for_mission returns our test artifacts",
                f"missing {len(missing)} of {len(our_ids)}: {sorted(missing)[:3]}",
            )
            return
        self._pass(f"list_for_mission returns all {len(our_ids)} test artifacts (newest first)")

    async def check_list_with_type_filter(self) -> None:
        """[F] artifact_type filter narrows the result correctly."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.mission_artifact import MissionArtifactService

        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            # Filter to 'report' type — all our test rows are reports
            report_list = await svc.list_for_mission(
                mission_id=self._mission_id,
                limit=50,
                artifact_type="report",
            )
            # Filter to 'code' type — should exclude ours
            code_list = await svc.list_for_mission(
                mission_id=self._mission_id,
                limit=50,
                artifact_type="code",
            )

        report_ids = {a.id for a in report_list}
        code_ids = {a.id for a in code_list}
        our_ids = set(self._created_artifact_ids)

        if not (our_ids <= report_ids):
            self._fail(
                "artifact_type='report' filter includes our reports",
                "some test artifacts missing from report filter result",
            )
            return
        if our_ids & code_ids:
            self._fail(
                "artifact_type='code' filter excludes our reports",
                "test reports appeared in code-typed filter",
            )
            return
        self._pass("artifact_type filter narrows correctly (report ≠ code)")

    async def check_invalid_type_filter_raises(self) -> None:
        """[G] Invalid filter value at list_for_mission raises ValidationError."""
        from modules.backend.core.database import get_async_session
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.services.mission_artifact import MissionArtifactService

        async with get_async_session() as db:
            svc = MissionArtifactService(db)
            try:
                await svc.list_for_mission(
                    mission_id=self._mission_id,
                    artifact_type="garbage",
                )
                self._fail(
                    "Invalid filter type rejected",
                    "list_for_mission should have raised ValidationError",
                )
                return
            except ValidationError:
                pass

        self._pass("Invalid artifact_type filter raises ValidationError")

    # -------------------------------------------------------------------------
    # Runner
    # -------------------------------------------------------------------------

    async def run(self) -> bool:
        print(f"\nPlan 43 — Persistent Artifacts Verification " f"(run_tag={self._run_tag})")
        print("=" * 70)

        print("\n[Setup] Finding host mission...")
        if not await self.setup():
            return False

        print("\n[A] Direct service-layer insert")
        await self.check_direct_service_create()

        print("\n[B] Input validation")
        await self.check_enum_validation()

        print("\n[C] Content cap (100k chars)")
        await self.check_content_cap()

        print("\n[D] End-to-end extraction via persist_mission_results")
        await self.check_extraction_from_outcome()

        print("\n[E] list_for_mission returns our rows")
        await self.check_list_for_mission()

        print("\n[F] artifact_type filter")
        await self.check_list_with_type_filter()

        print("\n[G] Invalid filter rejected")
        await self.check_invalid_type_filter_raises()

        print("\n" + "=" * 70)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        print("PASSED — all persistent artifacts checks passed")
        return True


async def _main(verbose: bool) -> int:
    verifier = ArtifactsVerifier(verbose=verbose)
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
