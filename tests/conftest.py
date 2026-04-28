"""
Root Pytest Fixtures.

Shared fixtures available to all test types.

Test Database Configuration:
    Test DB params come from config/settings/test.yaml. To use PostgreSQL
    instead of the default in-memory SQLite, set the TEST_DATABASE_URL
    environment variable (see config/.env.example).
"""

from pydantic_ai import models as pydantic_ai_models

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid5, UUID

# Deterministic test UUIDs — use these instead of arbitrary strings in tests.
# Generated via uuid5 from a fixed namespace so they're stable across runs.
_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
TEST_USER_ID = str(uuid5(_TEST_NS, "user:test"))
TEST_USER_ID_2 = str(uuid5(_TEST_NS, "user:test-2"))
TEST_OWNER_ID = str(uuid5(_TEST_NS, "user:owner"))
TEST_ALICE_ID = str(uuid5(_TEST_NS, "user:alice"))
TEST_BOB_ID = str(uuid5(_TEST_NS, "user:bob"))
TEST_MISSION_ID = str(uuid5(_TEST_NS, "mission:test"))
TEST_SESSION_ID = str(uuid5(_TEST_NS, "session:test"))

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from redis.asyncio import Redis as AsyncRedis

from modules.backend.models.base import Base
import modules.backend.models.agent_catalog  # noqa: F401 — register tables
import modules.backend.models.api_key  # noqa: F401 — register tables
import modules.backend.models.execution  # noqa: F401 — register tables
import modules.backend.models.execution_environment  # noqa: F401 — register tables
import modules.backend.models.execution_record  # noqa: F401 — register tables
import modules.backend.models.mission  # noqa: F401 — register tables
import modules.backend.models.mission_context  # noqa: F401 — register tables
import modules.backend.models.mission_history  # noqa: F401 — register tables
import modules.backend.models.mission_team  # noqa: F401 — register tables
import modules.backend.models.prompt_version  # noqa: F401 — register tables
import modules.backend.models.session  # noqa: F401 — register tables
import modules.backend.models.user  # noqa: F401 — register tables
import modules.backend.models.workflow_definition  # noqa: F401 — register tables
import modules.backend.models.workflow_schedule  # noqa: F401 — register tables
import modules.backend.models.mission_intent  # noqa: F401 — register tables (Plan 57)
import modules.backend.models.mission_learning  # noqa: F401 — register tables (Plan 57)
import modules.backend.models.session_followup  # noqa: F401 — register tables (Plan 51)
from tests.test_config import get_test_database_url as _get_test_database_url
from tests.test_config import get_test_redis_url as _get_test_redis_url



# Event loop scope is set to "session" in pyproject.toml via
# asyncio_default_fixture_loop_scope. No manual event_loop fixture needed.


# =============================================================================
# Database Configuration (from config/settings/test.yaml or TEST_DATABASE_URL)
# =============================================================================


def get_test_database_url() -> str:
    """Get test database URL from env or config/settings/test.yaml."""
    return _get_test_database_url()


def is_sqlite() -> bool:
    """Check if using SQLite database."""
    return "sqlite" in get_test_database_url()


# =============================================================================
# Database Engine Fixtures
# =============================================================================


@pytest.fixture(scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Create the test database engine.

    For SQLite: Uses in-memory database with shared cache for connection reuse.
    For PostgreSQL: Creates tables at start, drops them at end.

    Scope is session to avoid recreating the engine for each test.
    """
    url = get_test_database_url()

    if is_sqlite():
        # SQLite in-memory requires special handling for async
        engine = create_async_engine(
            url,
            echo=False,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        # PostgreSQL
        engine = create_async_engine(
            url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )

    # Drop and recreate all tables for a clean slate.
    # Prevents stale data from prior runs contaminating tests.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="session")
def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create a session factory bound to the test engine.

    Scope is session to reuse the factory across tests.
    """
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# =============================================================================
# Database Session Fixtures
# =============================================================================


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session for a single test.

    Binds the session to a dedicated connection with an outer transaction
    that is always rolled back — full test isolation without DDL.

    The connection-bound session avoids asyncpg's "another operation
    is in progress" error that occurs with pooled connections.
    """
    async with db_engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await txn.rollback()


@pytest.fixture
async def db_session_committed(
    db_session_factory: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session that commits changes.

    Use this fixture when you need to test behavior that requires
    committed data (e.g., testing unique constraints, triggers).

    WARNING: Data persists until the end of the test session.
    Use sparingly and clean up after yourself.

    Usage:
        async def test_unique_constraint(db_session_committed: AsyncSession):
            user1 = User(email="test@example.com")
            db_session_committed.add(user1)
            await db_session_committed.commit()

            user2 = User(email="test@example.com")
            db_session_committed.add(user2)
            with pytest.raises(IntegrityError):
                await db_session_committed.commit()
    """
    async with db_session_factory() as session:
        yield session
        await session.commit()


# =============================================================================
# Test User Fixture
# =============================================================================


@pytest.fixture
async def test_user(db_session: AsyncSession) -> "modules.backend.models.user.User":
    """Create a test user in the database.

    Many service tests create missions/sessions that FK to users.id.
    This fixture ensures the referenced user row exists. Uses merge()
    so it's safe to call multiple times across session-scoped loops.
    """
    from modules.backend.core import security
    from modules.backend.models.user import User

    user = User(
        id=TEST_USER_ID,
        email="test@mission-control.dev",
        display_name="Test User",
        hashed_password=security.hash_password("test-password"),
        system_role="user",
        is_active=True,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


@pytest.fixture
async def test_user_2(db_session: AsyncSession) -> "modules.backend.models.user.User":
    """Create a second test user for tests that need multiple users."""
    from modules.backend.core import security
    from modules.backend.models.user import User

    user = User(
        id=TEST_USER_ID_2,
        email="test2@mission-control.dev",
        display_name="Test User 2",
        hashed_password=security.hash_password("test-password-2"),
        system_role="user",
        is_active=True,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


# =============================================================================
# Redis Fixtures
# =============================================================================


def get_test_redis_url() -> str:
    """Get test Redis URL from env or config/settings/test.yaml."""
    return _get_test_redis_url()


@pytest.fixture
async def redis() -> AsyncGenerator[AsyncRedis, None]:
    """
    Real Redis connection for a single test.

    Creates a fresh connection per test (function-scoped) to avoid
    event loop conflicts with session-scoped fixtures. Uses db 1
    (from test.yaml) to isolate test data from development.

    Flushes the test database after each test for isolation.
    """
    url = get_test_redis_url()
    client = AsyncRedis.from_url(url, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not available: {exc}")
    yield client
    await client.flushdb()
    await client.close()


# =============================================================================
# Test Settings Fixtures
# =============================================================================


@pytest.fixture
def test_settings() -> dict[str, Any]:
    """
    Provide test-specific settings.

    These can be used to override application settings during tests.
    """
    return {
        "app_name": "Test Application",
        "app_env": "test",
        "app_debug": True,
        "app_log_level": "DEBUG",
        "jwt_secret": "test-secret-key-for-testing-only",
        "jwt_algorithm": "HS256",
        "jwt_access_token_expire_minutes": 5,
        "api_key_salt": "test-salt",
    }


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def anyio_backend() -> str:
    """Specify the async backend for anyio."""
    return "asyncio"
