"""Migration plan88_003: mission_schedules replaces workflow_schedules (Plan 88 step 88.1.3).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The base tables predate Alembic, so the chain cannot
run from an empty database: the scratch database is built from the current
models, completed with the failure columns that plan88_002 creates but the
models do not map until 88.2.3b, stamped plan88_003 and downgraded to
plan88_002, which recreates an empty workflow_schedules. Each test seeds a
workflow_schedules row at plan88_002, then upgrades. The tests are synchronous
because Alembic's env.py drives its own event loop.
"""

import asyncio
import uuid
from collections.abc import Iterator
from unittest.mock import patch

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import modules.backend.models  # noqa: F401 — register tables
from modules.backend.core.config import find_project_root
from modules.backend.models.base import Base
from tests.test_config import get_test_database_url

pytestmark = pytest.mark.integration

_PREVIOUS = "plan88_002"
_TARGET = "plan88_003"

# plan88_002 creates these; the models map them only from 88.2.3b.
_UNMAPPED_FAILURE_DDL = (
    "ALTER TABLE tasks ADD COLUMN failure_origin VARCHAR(32), "
    "ADD COLUMN failure_class VARCHAR(40), ADD COLUMN failure_fingerprint VARCHAR(64)",
    "ALTER TABLE task_executions ADD COLUMN failure_origin VARCHAR(32), "
    "ADD COLUMN failure_class VARCHAR(40), ADD COLUMN failure_fingerprint VARCHAR(64), "
    "ADD COLUMN failure_json JSONB",
    "CREATE INDEX ix_task_executions_failure_fingerprint "
    "ON task_executions (failure_fingerprint)",
)


def _dsn(url: str) -> str:
    """asyncpg DSN for a SQLAlchemy URL."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _alembic(url: str, action: str, revision: str) -> None:
    script_location = find_project_root() / "modules" / "backend" / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    with patch("modules.backend.core.config.get_database_url", return_value=url):
        getattr(command, action)(cfg, revision)


async def _execute(url: str, *statements: tuple) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        for sql, *args in statements:
            await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _fetch(url: str, sql: str, *args) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _create_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for ddl in _UNMAPPED_FAILURE_DDL:
                await conn.execute(text(ddl))
    finally:
        await engine.dispose()


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """A fresh database migrated to plan88_002; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_003_{uuid.uuid4().hex[:12]}"
    server_url = test_url.render_as_string(hide_password=False)
    asyncio.run(_execute(server_url, (f'CREATE DATABASE "{name}"',)))
    url = test_url.set(database=name).render_as_string(hide_password=False)
    try:
        asyncio.run(_create_schema(url))
        _alembic(url, "stamp", _TARGET)
        _alembic(url, "downgrade", _PREVIOUS)
        yield url
    finally:
        asyncio.run(_execute(server_url, (f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',)))


def _seed_user(url: str) -> str:
    user_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO users (id, email, display_name, system_role, is_active, "
                "is_service_account, token_version, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'user', true, false, 0, now(), now())",
                user_id,
                f"p88-003-{user_id.hex[:8]}@mission-control.dev",
            ),
        )
    )
    return str(user_id)


def _seed_mission(url: str, owner_id: str) -> tuple[str, str]:
    """Insert a mission owned by ``owner_id`` and a definition; return their ids."""
    mission_id = uuid.uuid4()
    definition_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', now(), now())",
                mission_id,
                f"p88-003-{str(mission_id)[:8]}",
                owner_id,
            ),
            (
                "INSERT INTO workflow_definitions (id, mission_id, name, description, version, "
                "enabled, objective, steps, edges_json, canvas_state, trigger_config, "
                "budget_config, parameters, context, created_at, updated_at) "
                "VALUES ($1, $2, 'wf', '', 1, true, '{}', '[]', '[]', '{}', '{}', '{}', "
                "'[]', '{}', now(), now())",
                definition_id,
                mission_id,
            ),
        )
    )
    return str(mission_id), str(definition_id)


def _seed_schedule(
    url: str,
    mission_id: str,
    definition_id: str,
    *,
    timezone: str = "UTC",
    iteration_count: int = 0,
    max_iterations: int | None = None,
    created_by: str = "user:api",
    cron_expression: str = "0 9 * * *",
) -> str:
    schedule_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO workflow_schedules (id, workflow_definition_id, mission_id, "
                "cron_expression, timezone, enabled, description, budget_per_run_usd, "
                "max_iterations, iteration_count, cooldown_seconds, created_by, "
                "created_at, updated_at) "
                "VALUES ($1, $2, $3, $8, $4, true, 'legacy', 1.5, $5, $6, 0, $7, "
                "now(), now())",
                schedule_id,
                uuid.UUID(definition_id),
                uuid.UUID(mission_id),
                timezone,
                max_iterations,
                iteration_count,
                created_by,
                cron_expression,
            ),
        )
    )
    return str(schedule_id)


def _mission_schedules(url: str, mission_id: str) -> list[asyncpg.Record]:
    return asyncio.run(
        _fetch(
            url,
            "SELECT * FROM mission_schedules WHERE mission_id = $1 ORDER BY created_at",
            uuid.UUID(mission_id),
        )
    )


def _table_exists(url: str, table: str) -> bool:
    rows = asyncio.run(_fetch(url, "SELECT to_regclass($1) AS oid", table))
    return rows[0]["oid"] is not None


def test_row_migrates_paused(scratch_db: str):
    owner = _seed_user(scratch_db)
    mission_id, definition_id = _seed_mission(scratch_db, owner)
    legacy_id = _seed_schedule(
        scratch_db,
        mission_id,
        definition_id,
        timezone="Europe/London",
        iteration_count=3,
        max_iterations=10,
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    [row] = _mission_schedules(scratch_db, mission_id)
    assert row["status"] == "PAUSED"
    assert row["completed_reason"] is None
    assert row["executed_run_count"] == 3
    assert row["max_runs"] == 10
    assert row["kind"] == "WORKFLOW_DEFINITION"
    assert row["catch_up_window_seconds"] == 21600
    assert row["time_zone_name"] == "Europe/London"
    assert row["cron_expression"] == "0 9 * * *"
    assert str(row["workflow_definition_id"]) == definition_id
    assert row["objective_template"] is None
    assert row["name"] == f"wf-{legacy_id[:8]}"
    assert row["temporal_schedule_id"] == f"mission-schedule-{row['id']}"
    assert row["temporal_sync_state"] == "PENDING"


def test_exhausted_row_completes(scratch_db: str):
    owner = _seed_user(scratch_db)
    mission_id, definition_id = _seed_mission(scratch_db, owner)
    _seed_schedule(scratch_db, mission_id, definition_id, iteration_count=10, max_iterations=10)

    _alembic(scratch_db, "upgrade", _TARGET)

    [row] = _mission_schedules(scratch_db, mission_id)
    assert row["status"] == "COMPLETED"
    assert row["completed_reason"] == "MAX_RUNS_REACHED"
    assert row["executed_run_count"] == 10


def test_invalid_timezone_archived(scratch_db: str):
    owner = _seed_user(scratch_db)
    mission_id, definition_id = _seed_mission(scratch_db, owner)
    _seed_schedule(scratch_db, mission_id, definition_id, timezone="Mars/Base")

    _alembic(scratch_db, "upgrade", _TARGET)

    [row] = _mission_schedules(scratch_db, mission_id)
    assert row["status"] == "ARCHIVED"
    assert row["time_zone_name"] == "UTC"
    assert row["temporal_sync_error"] == "plan88_003: invalid time zone Mars/Base"


def test_created_by_parsed(scratch_db: str):
    owner = _seed_user(scratch_db)
    creator = _seed_user(scratch_db)
    mission_id, definition_id = _seed_mission(scratch_db, owner)
    by_creator = _seed_schedule(scratch_db, mission_id, definition_id, created_by=f"user:{creator}")
    by_api = _seed_schedule(
        scratch_db, mission_id, definition_id, created_by="user:api", cron_expression="0 10 * * *"
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    creators = {
        r["name"]: str(r["created_by_user_id"]) for r in _mission_schedules(scratch_db, mission_id)
    }
    assert creators == {f"wf-{by_creator[:8]}": creator, f"wf-{by_api[:8]}": owner}


def test_unresolvable_creator_aborts(scratch_db: str):
    mission_id, definition_id = _seed_mission(scratch_db, "cli-user")
    legacy_id = _seed_schedule(scratch_db, mission_id, definition_id, created_by="user:api")

    with pytest.raises(RuntimeError, match=legacy_id):
        _alembic(scratch_db, "upgrade", _TARGET)

    assert _table_exists(scratch_db, "workflow_schedules")
    assert not _table_exists(scratch_db, "mission_schedules")


def test_workflow_schedules_dropped(scratch_db: str):
    owner = _seed_user(scratch_db)
    mission_id, definition_id = _seed_mission(scratch_db, owner)
    _seed_schedule(scratch_db, mission_id, definition_id)

    _alembic(scratch_db, "upgrade", _TARGET)

    assert not _table_exists(scratch_db, "workflow_schedules")
    fk = asyncio.run(
        _fetch(
            scratch_db,
            "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conname = 'fk_mission_runs_schedule_id'",
        )
    )
    assert len(fk) == 1
    assert "ON DELETE SET NULL" in fk[0]["def"]
