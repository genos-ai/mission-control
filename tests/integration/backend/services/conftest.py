"""Shared fixtures for service integration tests.

All tests use a real PostgreSQL database — no mocks.
Each test gets an isolated session that rolls back on teardown.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.user import User
from tests.conftest import TEST_MISSION_ID, TEST_USER_ID, TEST_USER_ID_2


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create a real admin user in the database."""
    hashed = security.hash_password("admin-password-123")
    user = User(
        id=TEST_USER_ID_2,
        email="admin@test.dev",
        display_name="Test Admin",
        hashed_password=hashed,
        system_role="admin",
        is_active=True,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Create a real regular user in the database."""
    hashed = security.hash_password("user-password-123")
    user = User(
        id=TEST_USER_ID,
        email="user@test.dev",
        display_name="Test User",
        hashed_password=hashed,
        system_role="user",
        is_active=True,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Create a deactivated user in the database."""
    from uuid import UUID, uuid5

    inactive_id = str(uuid5(UUID("00000000-0000-0000-0000-000000000000"), "user:inactive"))
    hashed = security.hash_password("inactive-pass-123")
    user = User(
        id=inactive_id,
        email="inactive@test.dev",
        display_name="Inactive User",
        hashed_password=hashed,
        system_role="user",
        is_active=False,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


@pytest.fixture
async def test_mission(db_session: AsyncSession, regular_user: User) -> Mission:
    """Create a real mission owned by regular_user."""
    mission = Mission(
        id=TEST_MISSION_ID,
        name="test-mission",
        description="A test mission for integration tests",
        owner_id=regular_user.id,
        status=MissionStatus.ACTIVE,
    )
    mission = await db_session.merge(mission)
    await db_session.flush()
    db_session.add(
        MissionPlan(
            mission_id=mission.id,
            gate_mode=GateMode.MANUAL,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
        )
    )
    await db_session.flush()
    return mission


@pytest.fixture
async def archived_mission(db_session: AsyncSession, regular_user: User) -> Mission:
    """Create an archived mission."""
    from uuid import UUID, uuid5

    archived_id = str(uuid5(UUID("00000000-0000-0000-0000-000000000000"), "mission:archived"))
    mission = Mission(
        id=archived_id,
        name="archived-mission",
        description="An archived mission",
        owner_id=regular_user.id,
        status=MissionStatus.ARCHIVED,
    )
    mission = await db_session.merge(mission)
    await db_session.flush()
    db_session.add(
        MissionPlan(
            mission_id=mission.id,
            gate_mode=GateMode.MANUAL,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
        )
    )
    await db_session.flush()
    return mission
