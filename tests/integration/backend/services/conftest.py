"""Shared fixtures for service integration tests.

All tests use a real in-memory SQLite database — no mocks.
Each test gets an isolated session that rolls back on teardown.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.user import User


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create a real admin user in the database."""
    hashed = security.hash_password("admin-password-123")
    user = User(
        id="admin-001",
        email="admin@test.dev",
        display_name="Test Admin",
        hashed_password=hashed,
        system_role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Create a real regular user in the database."""
    hashed = security.hash_password("user-password-123")
    user = User(
        id="user-001",
        email="user@test.dev",
        display_name="Test User",
        hashed_password=hashed,
        system_role="user",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Create a deactivated user in the database."""
    hashed = security.hash_password("inactive-pass-123")
    user = User(
        id="user-inactive",
        email="inactive@test.dev",
        display_name="Inactive User",
        hashed_password=hashed,
        system_role="user",
        is_active=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def test_mission(db_session: AsyncSession, regular_user: User) -> Mission:
    """Create a real mission owned by regular_user."""
    mission = Mission(
        id="mission-001",
        name="test-mission",
        description="A test mission for integration tests",
        owner_id=regular_user.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(mission)
    await db_session.flush()
    return mission


@pytest.fixture
async def archived_mission(db_session: AsyncSession, regular_user: User) -> Mission:
    """Create an archived mission."""
    mission = Mission(
        id="mission-archived",
        name="archived-mission",
        description="An archived mission",
        owner_id=regular_user.id,
        status=MissionStatus.ARCHIVED,
    )
    db_session.add(mission)
    await db_session.flush()
    return mission
