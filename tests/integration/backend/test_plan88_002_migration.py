"""Migration plan88_002: mission runs and run linking columns (Plan 88 step 88.1.2).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The base tables predate Alembic, so the chain cannot
run from an empty database: the scratch database is built from the current
models, completed with the failure columns that plan88_002 creates but the
models do not map until 88.2.3b, stamped plan88_002 and downgraded to
plan88_001. The tests are synchronous because Alembic's env.py drives its own
event loop.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

import modules.backend.models  # noqa: F401 — register tables
from modules.backend.core.config import find_project_root
from modules.backend.models.base import Base
from tests.test_config import get_test_database_url

pytestmark = pytest.mark.integration

_PREVIOUS = "plan88_001"
_TARGET = "plan88_002"

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

_FAILURE_COLUMNS = {
    ("tasks", "failure_origin"),
    ("tasks", "failure_class"),
    ("tasks", "failure_fingerprint"),
    ("task_executions", "failure_origin"),
    ("task_executions", "failure_class"),
    ("task_executions", "failure_fingerprint"),
    ("task_executions", "failure_json"),
}


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


async def _insert_run(url: str, params: dict) -> None:
    """Insert one mission_runs row through SQLAlchemy, so violations raise IntegrityError."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO mission_runs (id, mission_id, plan_id, sequence, trigger, "
                    "status, schedule_id, scheduled_for, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :mission_id, :plan_id, :sequence, :trigger, "
                    ":status, NULL, NULL, now(), now())"
                ),
                params,
            )
    finally:
        await engine.dispose()


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """A fresh database migrated to plan88_001; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_002_{uuid.uuid4().hex[:12]}"
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


def _seed_mission(url: str) -> tuple[str, str]:
    """Insert a mission and its plan; return (mission_id, plan_id)."""
    mission_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', now(), now())",
                mission_id,
                f"p88-002-{str(mission_id)[:8]}",
                str(uuid.uuid4()),
            ),
            (
                "INSERT INTO mission_plans (id, mission_id, gate_mode, total_spent_usd, "
                "created_at, updated_at) VALUES ($1, $2, 'MANUAL', 0, now(), now())",
                plan_id,
                mission_id,
            ),
        )
    )
    return str(mission_id), str(plan_id)


def _columns(url: str, table: str) -> set[str]:
    rows = asyncio.run(
        _fetch(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table,
        )
    )
    return {r["column_name"] for r in rows}


def _index_def(url: str, index_name: str) -> str | None:
    rows = asyncio.run(
        _fetch(url, "SELECT indexdef FROM pg_indexes WHERE indexname = $1", index_name)
    )
    return rows[0]["indexdef"] if rows else None


def test_upgrade_downgrade_roundtrip(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)
    assert "mission_run_id" in _columns(scratch_db, "tasks")

    _alembic(scratch_db, "downgrade", _PREVIOUS)
    assert _columns(scratch_db, "mission_runs") == set()
    assert "parent_execution_record_id" in _columns(scratch_db, "execution_records")

    _alembic(scratch_db, "upgrade", _TARGET)
    assert "parent_execution_record_id" not in _columns(scratch_db, "execution_records")
    assert "run_sequence_counter" in _columns(scratch_db, "missions")


def test_one_active_run_per_mission(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)
    mission_id, plan_id = _seed_mission(scratch_db)
    base = {"mission_id": mission_id, "plan_id": plan_id, "trigger": "MANUAL"}
    asyncio.run(_insert_run(scratch_db, {**base, "sequence": 1, "status": "PENDING"}))

    with pytest.raises(IntegrityError, match="uq_mission_runs_one_active"):
        asyncio.run(_insert_run(scratch_db, {**base, "sequence": 2, "status": "RUNNING"}))

    asyncio.run(_insert_run(scratch_db, {**base, "sequence": 3, "status": "SKIPPED"}))


def test_schedule_slot_check(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)
    mission_id, plan_id = _seed_mission(scratch_db)

    with pytest.raises(IntegrityError, match="ck_mission_runs_schedule_slot"):
        asyncio.run(
            _insert_run(
                scratch_db,
                {
                    "mission_id": mission_id,
                    "plan_id": plan_id,
                    "sequence": 1,
                    "trigger": "SCHEDULE",
                    "status": "PENDING",
                },
            )
        )


def test_llm_calls_attribution_columns_exist(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)

    assert {"mission_run_id", "task_id"} <= _columns(scratch_db, "llm_calls")


def test_context_version_index_exists(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)

    indexdef = _index_def(scratch_db, "ix_context_changes_context_version")

    assert indexdef is not None
    assert "context_changes" in indexdef
    assert "(context_id, version)" in indexdef


def test_failure_columns_exist(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)

    present = {
        (table, column)
        for table in ("tasks", "task_executions")
        for column in _columns(scratch_db, table)
    }

    assert _FAILURE_COLUMNS <= present
    assert _index_def(scratch_db, "ix_task_executions_failure_fingerprint") is not None
