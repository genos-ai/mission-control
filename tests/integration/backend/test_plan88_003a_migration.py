"""Migration plan88_003a: repair inflated failure learnings (Plan 88 step 88.3.4).

Runs Alembic against a scratch PostgreSQL database created on the test server
and dropped afterwards. The scratch database is built from the current models,
stamped plan88_003a and downgraded to plan88_003 (a no-op). Each test seeds
mission_learnings rows in the pre-88.3.4 shape, then upgrades. The tests are
synchronous because Alembic's env.py drives its own event loop.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import patch

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import modules.backend.models  # noqa: F401 — register tables
from modules.backend.core.config import find_project_root
from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base
from tests.test_config import get_test_database_url

pytestmark = pytest.mark.integration

_PREVIOUS = "plan88_003"
_TARGET = "plan88_003a"
_AGENT = "software.quality.agent"


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
    """A fresh database at plan88_003; yields its SQLAlchemy URL."""
    test_url = make_url(get_test_database_url())
    name = f"mc_plan88_003a_{uuid.uuid4().hex[:12]}"
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


def _seed_mission(url: str) -> str:
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
                f"p88-003a-{user_id.hex[:8]}@mission-control.dev",
            ),
            (
                "INSERT INTO missions (id, name, description, status, owner_id, "
                "default_roster, created_at, updated_at) "
                "VALUES ($1, $2, 'Migration test', 'ACTIVE', $3, 'default', now(), now())",
                mission_id,
                f"p88-003a-{str(mission_id)[:8]}",
                str(user_id),
            ),
        )
    )
    return str(mission_id)


def _seed_learning(
    url: str,
    mission_id: str,
    *,
    kind: str,
    attempt_ids: list[str],
    tier: str | None = "FailureTier.TIER_1_STRUCTURAL",
    occurrence_count: int = 58,
    recommendation: str = "Recurring failure pattern — consider a different agent or approach.",
    age_minutes: int = 0,
) -> str:
    learning_id = uuid.uuid4()
    evidence = {"task_attempt_ids": attempt_ids, "execution_ids": ["exec-1"]}
    if tier is not None:
        evidence["failure_tiers"] = [tier]
    stamp = utc_now() - timedelta(minutes=age_minutes)
    asyncio.run(
        _execute(
            url,
            (
                "INSERT INTO mission_learnings (id, mission_id, kind, title, body, "
                "recommendation, evidence, domain_tags, agent_names, confidence, "
                "occurrence_count, platform_promoted, status, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, 'body', $5, $6::json, '[]'::json, $7::json, 0.95, "
                "$8, false, 'active', $9, $9)",
                learning_id,
                uuid.UUID(mission_id),
                kind,
                f"{_AGENT} — {tier} failures ({occurrence_count}x)",
                recommendation,
                json.dumps(evidence),
                json.dumps([_AGENT]),
                occurrence_count,
                stamp,
            ),
        )
    )
    return str(learning_id)


def _learning(url: str, learning_id: str) -> asyncpg.Record:
    [row] = asyncio.run(
        _fetch(url, "SELECT * FROM mission_learnings WHERE id = $1", uuid.UUID(learning_id))
    )
    return row


def test_count_derived_and_tier_normalised(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    learning_id = _seed_learning(
        scratch_db, mission_id, kind="failure_pattern", attempt_ids=["a1", "a2", "a3"]
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    row = _learning(scratch_db, learning_id)
    assert row["occurrence_count"] == 3
    assert float(row["confidence"]) == pytest.approx(0.75)
    assert row["title"] == f"{_AGENT} — tier_1_structural failures (3x)"
    assert json.loads(row["evidence"])["failure_tiers"] == ["tier_1_structural"]
    assert row["status"] == "active"


def test_duplicates_merged_into_newest(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    older = _seed_learning(
        scratch_db, mission_id, kind="failure_pattern", attempt_ids=["a1", "a2"], age_minutes=60
    )
    newer = _seed_learning(
        scratch_db,
        mission_id,
        kind="retry_strategy",
        attempt_ids=["a2", "a3"],
        tier="tier_1_structural",
        recommendation="Retry with feedback: Fix the validation",
    )

    _alembic(scratch_db, "upgrade", _TARGET)

    survivor = _learning(scratch_db, newer)
    assert survivor["status"] == "active"
    assert survivor["kind"] == "retry_strategy"
    assert survivor["recommendation"] == "Retry with feedback: Fix the validation"
    assert json.loads(survivor["evidence"])["task_attempt_ids"] == ["a2", "a3", "a1"]
    assert survivor["occurrence_count"] == 3
    assert _learning(scratch_db, older)["status"] == "superseded"


def test_kind_flip_rewrites_failure_recommendation(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    older = _seed_learning(
        scratch_db, mission_id, kind="retry_strategy", attempt_ids=["a1"], age_minutes=60
    )
    newer = _seed_learning(scratch_db, mission_id, kind="failure_pattern", attempt_ids=["a2"])

    _alembic(scratch_db, "upgrade", _TARGET)

    survivor = _learning(scratch_db, newer)
    assert survivor["kind"] == "retry_strategy"
    assert survivor["recommendation"].startswith("Agent eventually succeeded")
    assert _learning(scratch_db, older)["status"] == "superseded"


def test_other_kinds_untouched_and_rerun_idempotent(scratch_db: str):
    mission_id = _seed_mission(scratch_db)
    finding = _seed_learning(scratch_db, mission_id, kind="finding", attempt_ids=["a1"])
    failure = _seed_learning(scratch_db, mission_id, kind="failure_pattern", attempt_ids=["a1"])

    _alembic(scratch_db, "upgrade", _TARGET)
    first = _learning(scratch_db, failure)
    _alembic(scratch_db, "downgrade", _PREVIOUS)
    _alembic(scratch_db, "upgrade", _TARGET)

    assert _learning(scratch_db, failure)["updated_at"] == first["updated_at"]
    assert _learning(scratch_db, finding)["occurrence_count"] == 58
