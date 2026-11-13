"""Migration plan88_005: mission lifecycle columns, plan status removed (Plan 88 step 88.4.2).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The scratch database is built from the current models,
stamped plan88_005 and downgraded to plan88_004, which restores mission_plans.status
and the iteration columns and drops the pause columns. Each test seeds rows in the
pre-88.4.2 shape, then upgrades. The tests are synchronous because Alembic's env.py
drives its own event loop.
"""

import asyncio
import uuid
from collections.abc import Iterator
from unittest.mock import patch

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import modules.backend.models  # noqa: F401 — register tables
from modules.backend.core.config import find_project_root
from modules.backend.models.base import Base
from tests.test_config import get_test_database_url

pytestmark = pytest.mark.integration

_PREVIOUS = "plan88_004"
_TARGET = "plan88_005"


def _dsn(url: str) -> str:
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
    finally:
        await engine.dispose()


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """A fresh database at plan88_004; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_005_{uuid.uuid4().hex[:12]}"
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


def _seed_mission(url: str, status: str) -> uuid.UUID:
    """A user, a mission in `status` and its plan in the plan88_004 shape; return the mission id."""
    user_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO users (id, email, display_name, system_role, is_active, "
                "is_service_account, token_version, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'user', true, false, 0, now(), now())",
                user_id,
                f"p88-005-{user_id.hex[:8]}@mission-control.dev",
            ),
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', $3, $4, 'default', now(), now())",
                mission_id,
                f"p88-005-{str(mission_id)[:8]}",
                status,
                str(user_id),
            ),
            (
                "INSERT INTO mission_plans (id, mission_id, gate_mode, status, "
                "budget_per_run_usd, budget_per_month_usd, created_at, updated_at) "
                "VALUES ($1, $2, 'MANUAL', 'COMPLETED', 5.0, 100.0, now(), now())",
                uuid.uuid4(),
                mission_id,
            ),
        )
    )
    return mission_id


def _mission(url: str, mission_id: uuid.UUID) -> asyncpg.Record:
    [row] = asyncio.run(_fetch(url, "SELECT * FROM missions WHERE id = $1", mission_id))
    return row


def _columns(url: str, table: str) -> set[str]:
    rows = asyncio.run(
        _fetch(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table,
        )
    )
    return {row["column_name"] for row in rows}


def test_paused_missions_get_user_reason(scratch_db: str):
    paused = _seed_mission(scratch_db, "PAUSED")
    active = _seed_mission(scratch_db, "ACTIVE")

    _alembic(scratch_db, "upgrade", _TARGET)

    paused_row = _mission(scratch_db, paused)
    assert paused_row["paused_reason"] == "USER"
    assert paused_row["paused_at"] is not None
    assert paused_row["paused_by_user_id"] is None
    active_row = _mission(scratch_db, active)
    assert active_row["paused_reason"] is None
    assert active_row["paused_at"] is None
    assert not {"status", "supervisor_iteration_count", "max_supervisor_iterations"} & (
        _columns(scratch_db, "mission_plans")
    )


def test_check_rejects_paused_without_reason(scratch_db: str):
    mission_id = _seed_mission(scratch_db, "ACTIVE")
    _alembic(scratch_db, "upgrade", _TARGET)

    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(
            _execute(
                scratch_db,
                ("UPDATE missions SET status = 'PAUSED' WHERE id = $1", mission_id),
            )
        )
    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(
            _execute(
                scratch_db,
                ("UPDATE missions SET paused_reason = 'USER' WHERE id = $1", mission_id),
            )
        )


def test_downgrade_restores_columns(scratch_db: str):
    mission_id = _seed_mission(scratch_db, "PAUSED")
    _alembic(scratch_db, "upgrade", _TARGET)
    _alembic(scratch_db, "downgrade", _PREVIOUS)

    plan_columns = _columns(scratch_db, "mission_plans")
    assert {"status", "supervisor_iteration_count", "max_supervisor_iterations"} <= plan_columns
    assert not {"paused_reason", "paused_at", "paused_by_user_id"} & (
        _columns(scratch_db, "missions")
    )
    [plan] = asyncio.run(
        _fetch(scratch_db, "SELECT * FROM mission_plans WHERE mission_id = $1", mission_id)
    )
    assert plan["status"] == "ACTIVE"
    assert plan["supervisor_iteration_count"] == 0
    assert plan["max_supervisor_iterations"] == 20

    _alembic(scratch_db, "upgrade", _TARGET)
    assert _mission(scratch_db, mission_id)["paused_reason"] == "USER"
