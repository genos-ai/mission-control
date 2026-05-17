"""
Pre-migration validation for Plan 72: Promote Task to First-Class Entity.

Read-only audit script. Parses all task_plan_json blobs in mission_plans
and execution_records, reports data integrity issues, and exits non-zero
if any corruption is found. Run BEFORE the Alembic migration.

Usage:
    python scripts/validate_task_migration.py [--verbose] [--debug]

Exit codes:
    0 — all data valid, safe to migrate
    1 — corruption found, review output before proceeding
"""

import json
import sys
from pathlib import Path

import click

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from modules.backend.core.config import find_project_root  # noqa: E402
from modules.backend.core.logging import get_logger, setup_logging  # noqa: E402


logger = get_logger(__name__)


def _parse_json_blob(raw) -> dict | None:
    """Parse a JSON blob (may be dict or string). Returns None on failure."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


@click.command()
@click.option("--verbose", is_flag=True, help="Show per-plan details")
@click.option("--debug", is_flag=True, help="Enable debug logging")
def validate(verbose: bool, debug: bool) -> None:
    """Validate task_plan_json data integrity before Plan 72 migration."""
    import asyncio
    asyncio.run(_validate_async(verbose, debug))


async def _validate_async(verbose: bool, debug: bool) -> None:
    """Async validation logic."""
    from sqlalchemy import text
    from modules.backend.core.database import get_async_session

    setup_logging(verbose=verbose, debug=debug)

    issues: list[str] = []
    stats = {
        "plans_total": 0,
        "plans_with_json": 0,
        "plans_corrupt_json": 0,
        "plans_missing_tasks_key": 0,
        "tasks_total": 0,
        "task_states_total": 0,
        "task_states_orphaned": 0,
        "execution_records_with_json": 0,
        "execution_records_corrupt_json": 0,
    }

    async with get_async_session() as session:
        # ── Validate mission_plans.task_plan_json ──────────────────────────

        result = await session.execute(text(
            "SELECT id, mission_id, task_plan_json FROM mission_plans"
        ))
        plans = result.fetchall()
        stats["plans_total"] = len(plans)

        for plan_id, mission_id, task_plan_raw in plans:
            if task_plan_raw is None:
                continue
            stats["plans_with_json"] += 1

            parsed = _parse_json_blob(task_plan_raw)
            if parsed is None:
                stats["plans_corrupt_json"] += 1
                issues.append(
                    f"CORRUPT JSON: mission_plans.id={plan_id} "
                    f"(mission={mission_id})"
                )
                continue

            if "tasks" not in parsed:
                stats["plans_missing_tasks_key"] += 1
                issues.append(
                    f"MISSING 'tasks' KEY: mission_plans.id={plan_id} "
                    f"(mission={mission_id})"
                )
                continue

            tasks = parsed["tasks"]
            stats["tasks_total"] += len(tasks)

            # Validate each task has required fields
            for i, task in enumerate(tasks):
                if not isinstance(task, dict):
                    issues.append(
                        f"NON-DICT TASK: plan={plan_id} index={i}"
                    )
                    continue
                if "task_id" not in task:
                    issues.append(
                        f"MISSING task_id: plan={plan_id} index={i}"
                    )
                if "agent" not in task:
                    issues.append(
                        f"MISSING agent: plan={plan_id} "
                        f"task_id={task.get('task_id', '?')}"
                    )
                if "description" not in task:
                    issues.append(
                        f"MISSING description: plan={plan_id} "
                        f"task_id={task.get('task_id', '?')}"
                    )

            if verbose:
                click.echo(
                    f"  Plan {plan_id}: {len(tasks)} tasks OK"
                )

        # ── Validate plan_task_states orphans ──────────────────────────────

        result = await session.execute(text(
            "SELECT pts.id, pts.mission_plan_id, pts.task_id "
            "FROM plan_task_states pts "
            "LEFT JOIN mission_plans mp ON pts.mission_plan_id = mp.id "
            "WHERE mp.id IS NULL"
        ))
        orphaned_states = result.fetchall()
        stats["task_states_orphaned"] = len(orphaned_states)
        for state_id, plan_id, task_id in orphaned_states:
            issues.append(
                f"ORPHANED PlanTaskState: id={state_id} "
                f"plan_id={plan_id} task_id={task_id}"
            )

        # Count total task states
        result = await session.execute(text(
            "SELECT count(*) FROM plan_task_states"
        ))
        stats["task_states_total"] = result.scalar_one()

        # ── Validate execution_records.task_plan_json ──────────────────────

        result = await session.execute(text(
            "SELECT id, task_plan_json FROM execution_records "
            "WHERE task_plan_json IS NOT NULL"
        ))
        exec_records = result.fetchall()
        stats["execution_records_with_json"] = len(exec_records)

        for record_id, raw in exec_records:
            parsed = _parse_json_blob(raw)
            if parsed is None:
                stats["execution_records_corrupt_json"] += 1
                issues.append(
                    f"CORRUPT JSON: execution_records.id={record_id}"
                )

    # ── Report ─────────────────────────────────────────────────────────────

    click.echo("\n=== Plan 72 Pre-Migration Validation ===\n")
    click.echo(f"Plans total:                    {stats['plans_total']}")
    click.echo(f"Plans with task_plan_json:      {stats['plans_with_json']}")
    click.echo(f"Plans with corrupt JSON:        {stats['plans_corrupt_json']}")
    click.echo(f"Plans missing 'tasks' key:      {stats['plans_missing_tasks_key']}")
    click.echo(f"Tasks total (from JSON):        {stats['tasks_total']}")
    click.echo(f"PlanTaskState rows:             {stats['task_states_total']}")
    click.echo(f"PlanTaskState orphaned:         {stats['task_states_orphaned']}")
    click.echo(f"ExecutionRecords with JSON:     {stats['execution_records_with_json']}")
    click.echo(f"ExecutionRecords corrupt JSON:  {stats['execution_records_corrupt_json']}")

    if issues:
        click.echo(f"\n{'='*60}")
        click.echo(f"ISSUES FOUND: {len(issues)}")
        click.echo(f"{'='*60}\n")
        for issue in issues:
            click.echo(f"  - {issue}")
        click.echo(
            "\nReview issues above before running the migration. "
            "Corrupt records will have their task FKs set to NULL."
        )
        sys.exit(1)
    else:
        click.echo("\nAll data valid. Safe to migrate.")
        sys.exit(0)


if __name__ == "__main__":
    validate()
