"""Migration plan88_001: gate mode becomes the GateMode enum (Plan 88 step 88.1.0).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The early base tables predate Alembic, so the chain
cannot run from an empty database: the scratch database is built from the
current models (the plan88_001 schema), stamped plan88_001 and downgraded to
plan87_002, then seeded. The tests are synchronous because Alembic's env.py
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

_PREVIOUS = "plan87_002"
_TARGET = "plan88_001"


def _dsn(url: str) -> str:
    """asyncpg DSN for a SQLAlchemy URL."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _alembic(url: str, action: str, revision: str) -> None:
    script_location = find_project_root() / "modules" / "backend" / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    with patch("modules.backend.core.config.get_database_url", return_value=url):
        getattr(command, action)(cfg, revision)


async def _execute(url: str, *statements: tuple[str, ...]) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        for sql, *args in statements:
            await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _create_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _fetch(url: str, sql: str, *args) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """A fresh database migrated to plan87_002; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_001_{uuid.uuid4().hex[:12]}"
    asyncio.run(
        _execute(test_url.render_as_string(hide_password=False), (f'CREATE DATABASE "{name}"',))
    )
    url = test_url.set(database=name).render_as_string(hide_password=False)
    try:
        asyncio.run(_create_schema(url))
        _alembic(url, "stamp", _TARGET)
        _alembic(url, "downgrade", _PREVIOUS)
        yield url
    finally:
        asyncio.run(
            _execute(
                test_url.render_as_string(hide_password=False),
                (f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',),
            )
        )


def _seed_mission(
    url: str, *, mission_gate: str | None, plan_gate: str | None, with_plan: bool
) -> str:
    """Insert a mission and optionally its plan at plan87_002; return the mission id."""
    mission_id = str(uuid.uuid4())
    statements: list[tuple] = [
        (
            "INSERT INTO missions (id, name, description, status, owner_id, default_roster, "
            "gate_mode, created_at, updated_at) "
            "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', $4, now(), now())",
            uuid.UUID(mission_id),
            f"p88-mig-{mission_id[:8]}",
            str(uuid.uuid4()),
            mission_gate,
        )
    ]
    if with_plan:
        statements.append(
            (
                "INSERT INTO mission_plans (id, mission_id, gate_mode, total_spent_usd, "
                "created_at, updated_at) VALUES ($1, $2, $3, 0, now(), now())",
                uuid.uuid4(),
                uuid.UUID(mission_id),
                plan_gate,
            )
        )
    asyncio.run(_execute(url, *statements))
    return mission_id


def _plan_gate_modes(url: str, mission_id: str) -> list[str]:
    rows = asyncio.run(
        _fetch(
            url, "SELECT gate_mode FROM mission_plans WHERE mission_id = $1", uuid.UUID(mission_id)
        )
    )
    return [r["gate_mode"] for r in rows]


def test_plan_null_inherits_mission_mode(scratch_db: str):
    mission_id = _seed_mission(
        scratch_db, mission_gate="autonomous", plan_gate=None, with_plan=True
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _plan_gate_modes(scratch_db, mission_id) == ["AUTONOMOUS"]


def test_workflow_managed_becomes_manual(scratch_db: str):
    mission_id = _seed_mission(
        scratch_db, mission_gate=None, plan_gate="workflow_managed", with_plan=True
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _plan_gate_modes(scratch_db, mission_id) == ["MANUAL"]


def test_unknown_and_null_become_manual(scratch_db: str):
    unknown = _seed_mission(scratch_db, mission_gate=None, plan_gate="bogus", with_plan=True)
    null = _seed_mission(scratch_db, mission_gate=None, plan_gate=None, with_plan=True)

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _plan_gate_modes(scratch_db, unknown) == ["MANUAL"]
    assert _plan_gate_modes(scratch_db, null) == ["MANUAL"]


def test_mission_without_plan_gets_plan(scratch_db: str):
    with_mode = _seed_mission(
        scratch_db, mission_gate="interactive", plan_gate=None, with_plan=False
    )
    without_mode = _seed_mission(scratch_db, mission_gate=None, plan_gate=None, with_plan=False)

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _plan_gate_modes(scratch_db, with_mode) == ["INTERACTIVE"]
    assert _plan_gate_modes(scratch_db, without_mode) == ["MANUAL"]


def test_roundtrip(scratch_db: str):
    mission_id = _seed_mission(
        scratch_db, mission_gate="manual", plan_gate="ai_assisted", with_plan=True
    )

    _alembic(scratch_db, "upgrade", _TARGET)
    _alembic(scratch_db, "downgrade", _PREVIOUS)

    rows = asyncio.run(
        _fetch(scratch_db, "SELECT gate_mode FROM missions WHERE id = $1", uuid.UUID(mission_id))
    )
    assert rows[0]["gate_mode"] == "ai_assisted"
    assert _plan_gate_modes(scratch_db, mission_id) == ["ai_assisted"]

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _plan_gate_modes(scratch_db, mission_id) == ["AI_ASSISTED"]
