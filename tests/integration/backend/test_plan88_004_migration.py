"""Migration plan88_004: budget caps and ledger aggregates (Plan 88 step 88.4.1).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The scratch database is built from the current models,
stamped plan88_004 and downgraded to plan88_003a, which restores the old budget
columns. Each test seeds rows in the pre-88.4.1 shape, then upgrades. The tests
are synchronous because Alembic's env.py drives its own event loop.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import date
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

_PREVIOUS = "plan88_003a"
_TARGET = "plan88_004"


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
    """A fresh database at plan88_003a; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_004_{uuid.uuid4().hex[:12]}"
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


def _seed_plan(url: str, lifetime: float | None) -> tuple[uuid.UUID, uuid.UUID]:
    """A user, a mission and its plan in the plan88_003a shape; return (mission, plan) ids."""
    user_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO users (id, email, display_name, system_role, is_active, "
                "is_service_account, token_version, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'user', true, false, 0, now(), now())",
                user_id,
                f"p88-004-{user_id.hex[:8]}@mission-control.dev",
            ),
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, budget_ceiling_usd, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', 9.0, now(), now())",
                mission_id,
                f"p88-004-{str(mission_id)[:8]}",
                str(user_id),
            ),
            (
                "INSERT INTO mission_plans (id, mission_id, gate_mode, budget_usd_ceiling, "
                "total_spent_usd, created_at, updated_at) "
                "VALUES ($1, $2, 'MANUAL', $3, 1.5, now(), now())",
                plan_id,
                mission_id,
                lifetime,
            ),
        )
    )
    return mission_id, plan_id


def _seed_run(url: str, mission_id: uuid.UUID, plan_id: uuid.UUID, seq: int, status: str) -> str:
    run_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO mission_runs (id, mission_id, plan_id, sequence, trigger, status, "
                "created_at, updated_at) VALUES ($1, $2, $3, $4, 'MANUAL', $5, now(), now())",
                run_id,
                mission_id,
                plan_id,
                seq,
                status,
            ),
        )
    )
    return str(run_id)


def _plan(url: str, plan_id: uuid.UUID) -> asyncpg.Record:
    [row] = asyncio.run(_fetch(url, "SELECT * FROM mission_plans WHERE id = $1", plan_id))
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


def test_backfills_caps_from_constants(scratch_db: str):
    _, plan_id = _seed_plan(scratch_db, None)

    _alembic(scratch_db, "upgrade", _TARGET)

    row = _plan(scratch_db, plan_id)
    assert float(row["budget_per_run_usd"]) == 5.0
    assert float(row["budget_per_month_usd"]) == 100.0
    assert row["budget_lifetime_usd"] is None
    assert "total_spent_usd" not in row.keys()
    assert "budget_ceiling_usd" not in _columns(scratch_db, "missions")


def test_rename_preserves_lifetime_value(scratch_db: str):
    _, kept = _seed_plan(scratch_db, 42.5)
    _, zeroed = _seed_plan(scratch_db, 0.0)

    _alembic(scratch_db, "upgrade", _TARGET)

    assert float(_plan(scratch_db, kept)["budget_lifetime_usd"]) == 42.5
    assert _plan(scratch_db, zeroed)["budget_lifetime_usd"] is None


def test_active_run_cap_backfilled(scratch_db: str):
    mission_id, plan_id = _seed_plan(scratch_db, None)
    ended = _seed_run(scratch_db, mission_id, plan_id, 1, "SUCCEEDED")
    active = _seed_run(scratch_db, mission_id, plan_id, 2, "RUNNING")

    _alembic(scratch_db, "upgrade", _TARGET)

    rows = asyncio.run(
        _fetch(
            scratch_db,
            "SELECT id, budget_cap_usd FROM mission_runs WHERE mission_id = $1",
            mission_id,
        )
    )
    caps = {str(row["id"]): row["budget_cap_usd"] for row in rows}
    assert float(caps[active]) == 5.0
    assert caps[ended] is None


def test_uq_llm_daily_nulls_not_distinct(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)
    insert = (
        "INSERT INTO llm_call_daily_aggregates (day, mission_id, agent_name, model, provider, "
        "call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_5m_tokens, "
        "cache_write_1h_tokens, thinking_tokens, cost_usd) "
        "VALUES ($1, NULL, 'a', 'm', 'p', 1, 1, 1, 0, 0, 0, 0, 0.5)",
        date(2026, 11, 1),
    )
    asyncio.run(_execute(scratch_db, insert))

    with pytest.raises(asyncpg.UniqueViolationError):
        asyncio.run(_execute(scratch_db, insert))


def test_month_below_run_rejected_by_check(scratch_db: str):
    _, plan_id = _seed_plan(scratch_db, None)
    _alembic(scratch_db, "upgrade", _TARGET)

    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(
            _execute(
                scratch_db,
                (
                    "UPDATE mission_plans SET budget_per_month_usd = 1.0 WHERE id = $1",
                    plan_id,
                ),
            )
        )


def test_downgrade_restores_columns(scratch_db: str):
    _alembic(scratch_db, "upgrade", _TARGET)
    _alembic(scratch_db, "downgrade", _PREVIOUS)

    plan_columns = _columns(scratch_db, "mission_plans")
    assert {"budget_usd_ceiling", "total_spent_usd"} <= plan_columns
    assert not {"budget_per_run_usd", "budget_per_month_usd", "budget_lifetime_usd"} & (
        plan_columns
    )
    assert "budget_ceiling_usd" in _columns(scratch_db, "missions")
    assert not _columns(scratch_db, "llm_call_daily_aggregates")

    _alembic(scratch_db, "upgrade", _TARGET)
    assert "budget_lifetime_usd" in _columns(scratch_db, "mission_plans")
