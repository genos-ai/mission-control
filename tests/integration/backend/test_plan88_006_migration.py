"""Migration plan88_006: durable gate request columns (Plan 88 step 88.4.3).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The scratch database is built from the current models,
stamped plan88_007 and downgraded to plan88_005, which drops the notification
tables and the durable gate columns. Each test seeds rows in the pre-88.4.3
shape, then upgrades. The tests are synchronous because Alembic's env.py drives
its own event loop.
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

_PREVIOUS = "plan88_005"
_TARGET = "plan88_006"
_HEAD = "plan88_007"


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
    """A fresh database at plan88_005; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_006_{uuid.uuid4().hex[:12]}"
    server_url = test_url.render_as_string(hide_password=False)
    asyncio.run(_execute(server_url, (f'CREATE DATABASE "{name}"',)))
    url = test_url.set(database=name).render_as_string(hide_password=False)
    try:
        asyncio.run(_create_schema(url))
        _alembic(url, "stamp", _HEAD)
        _alembic(url, "downgrade", _PREVIOUS)
        yield url
    finally:
        asyncio.run(_execute(server_url, (f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',)))


def _columns(url: str, table: str) -> set[str]:
    rows = asyncio.run(
        _fetch(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            table,
        )
    )
    return {row["column_name"] for row in rows}


def _seed_mission(url: str) -> uuid.UUID:
    """A user and a mission owned by it; return the mission id."""
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
                f"p88-006-{user_id.hex[:8]}@mission-control.dev",
            ),
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', now(), now())",
                mission_id,
                f"p88-006-{str(mission_id)[:8]}",
                str(user_id),
            ),
        )
    )
    return mission_id


def _seed_gate(url: str, mission_id: uuid.UUID, status: str) -> uuid.UUID:
    gate_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO gate_requests (id, mission_id, gate_type, context_json, status, "
                "created_at) VALUES ($1, $2, 'post_run', '{}'::jsonb, $3, now())",
                gate_id,
                mission_id,
                status,
            ),
        )
    )
    return gate_id


def _gate_status(url: str, gate_id: uuid.UUID) -> str:
    [row] = asyncio.run(_fetch(url, "SELECT status FROM gate_requests WHERE id = $1", gate_id))
    return row["status"]


def test_legacy_pending_gates_cancelled(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    gates = {
        status: _seed_gate(scratch_db, mission_id, status)
        for status in ("PENDING", "TIMED_OUT", "DECIDED", "CANCELLED")
    }

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _gate_status(scratch_db, gates["PENDING"]) == "CANCELLED"
    assert _gate_status(scratch_db, gates["TIMED_OUT"]) == "CANCELLED"
    assert _gate_status(scratch_db, gates["DECIDED"]) == "DECIDED"
    assert _gate_status(scratch_db, gates["CANCELLED"]) == "CANCELLED"
    [width] = asyncio.run(
        _fetch(
            scratch_db,
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'gate_requests' AND column_name = 'status'",
        )
    )
    assert width["character_maximum_length"] == 32
    assert {
        "mission_run_id",
        "task_id",
        "escalate_at",
        "pause_at",
        "escalated_at",
        "decision_channel",
        "ai_recommendation_json",
    } <= _columns(scratch_db, "gate_requests")


def test_round_trip(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    _alembic(scratch_db, "upgrade", _TARGET)
    escalated = _seed_gate(scratch_db, mission_id, "ESCALATED")

    _alembic(scratch_db, "downgrade", _PREVIOUS)
    assert "mission_run_id" not in _columns(scratch_db, "gate_requests")
    assert _gate_status(scratch_db, escalated) == "PENDING"

    _alembic(scratch_db, "upgrade", _HEAD)
    assert "ai_recommendation_json" in _columns(scratch_db, "gate_requests")
