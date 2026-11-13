"""Migration plan88_007: notification and channel binding tables (Plan 88 step 88.4.3).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The scratch database is built from the current models,
stamped plan88_007 and downgraded to plan88_006, which drops the four tables.
Each test seeds missions, then upgrades. The tests are synchronous because
Alembic's env.py drives its own event loop.
"""

import asyncio
import json
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

_PREVIOUS = "plan88_006"
_TARGET = "plan88_007"


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
    """A fresh database at plan88_006; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_007_{uuid.uuid4().hex[:12]}"
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


_DEFAULT_KINDS = [
    "run_succeeded",
    "run_failed",
    "gate_waiting",
    "gate_escalated",
    "gate_timeout_paused",
    "budget_paused",
    "run_skipped",
    "run_missed",
]


def _seed_user(url: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO users (id, email, display_name, system_role, is_active, "
                "is_service_account, token_version, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'user', true, false, 0, now(), now())",
                user_id,
                f"p88-007-{user_id.hex[:8]}@mission-control.dev",
            ),
        )
    )
    return user_id


def _seed_mission(url: str, owner_id: str) -> uuid.UUID:
    mission_id = uuid.uuid4()
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', now(), now())",
                mission_id,
                f"p88-007-{str(mission_id)[:8]}",
                owner_id,
            ),
        )
    )
    return mission_id


def _recipients(url: str, mission_id: uuid.UUID) -> list[asyncpg.Record]:
    return asyncio.run(
        _fetch(
            url,
            "SELECT user_id, channel, kinds::text AS kinds "
            "FROM mission_notification_recipients WHERE mission_id = $1",
            mission_id,
        )
    )


def test_owner_recipient_backfilled_once(scratch_db: str):
    user_id = _seed_user(scratch_db)
    missions = [_seed_mission(scratch_db, str(user_id)) for _ in range(2)]

    _alembic(scratch_db, "upgrade", _TARGET)
    _alembic(scratch_db, "downgrade", _PREVIOUS)
    _alembic(scratch_db, "upgrade", _TARGET)

    for mission_id in missions:
        [row] = _recipients(scratch_db, mission_id)
        assert row["user_id"] == user_id
        assert row["channel"] == "TELEGRAM"
        assert json.loads(row["kinds"]) == _DEFAULT_KINDS


def test_non_uuid_owner_skipped(scratch_db: str):
    free_string = _seed_mission(scratch_db, "cli-admin")
    unknown_uuid = _seed_mission(scratch_db, str(uuid.uuid4()))

    _alembic(scratch_db, "upgrade", _TARGET)

    assert _recipients(scratch_db, free_string) == []
    assert _recipients(scratch_db, unknown_uuid) == []


def _insert_token(url: str, user_id: uuid.UUID, purpose: str, gate_id: uuid.UUID | None) -> None:
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO action_tokens (id, purpose, token_hash, user_id, channel, "
                "gate_request_id, expires_at, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, 'TELEGRAM', $5, now() + interval '1 hour', now(), now())",
                uuid.uuid4(),
                purpose,
                uuid.uuid4().hex + uuid.uuid4().hex,
                user_id,
                gate_id,
            ),
        )
    )


def test_action_token_check_requires_gate_for_gate_decision(scratch_db: str):
    user_id = _seed_user(scratch_db)
    mission_id = _seed_mission(scratch_db, str(user_id))
    _alembic(scratch_db, "upgrade", _TARGET)
    gate_id = uuid.uuid4()
    asyncio.run(
        _execute(
            scratch_db,
            (
                "INSERT INTO gate_requests (id, mission_id, gate_type, context_json, status, "
                "created_at) VALUES ($1, $2, 'post_run', '{}'::jsonb, 'DECIDED', now())",
                gate_id,
                mission_id,
            ),
        )
    )

    with pytest.raises(asyncpg.CheckViolationError):
        _insert_token(scratch_db, user_id, "GATE_DECISION", None)
    with pytest.raises(asyncpg.CheckViolationError):
        _insert_token(scratch_db, user_id, "CHANNEL_LINK", gate_id)
    _insert_token(scratch_db, user_id, "GATE_DECISION", gate_id)
    _insert_token(scratch_db, user_id, "CHANNEL_LINK", None)


def test_identity_verified_at_nullable(scratch_db: str):
    user_id = _seed_user(scratch_db)
    _alembic(scratch_db, "upgrade", _TARGET)

    asyncio.run(
        _execute(
            scratch_db,
            (
                "INSERT INTO user_channel_identities (id, user_id, channel, external_id, "
                "created_at, updated_at) VALUES ($1, $2, 'TELEGRAM', '12345', now(), now())",
                uuid.uuid4(),
                user_id,
            ),
        )
    )
    [row] = asyncio.run(
        _fetch(
            scratch_db,
            "SELECT verified_at, external_username FROM user_channel_identities "
            "WHERE user_id = $1",
            user_id,
        )
    )
    assert row["verified_at"] is None
    assert row["external_username"] is None
    with pytest.raises(asyncpg.UniqueViolationError):
        asyncio.run(
            _execute(
                scratch_db,
                (
                    "INSERT INTO user_channel_identities (id, user_id, channel, external_id, "
                    "created_at, updated_at) VALUES ($1, $2, 'TELEGRAM', '67890', now(), now())",
                    uuid.uuid4(),
                    user_id,
                ),
            )
        )
