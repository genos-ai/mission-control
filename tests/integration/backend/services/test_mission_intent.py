"""
Integration tests for MissionIntentService.

Real database, no mocks (P12). Tests the full create → dedup → list → count
lifecycle against the DB.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.user import User
from modules.backend.core import security
from modules.backend.services.mission_intent import MissionIntentService


from uuid import uuid5, UUID
_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_INTENT_USER_ID = str(uuid5(_TEST_NS, "user:intent-tester"))
_INTENT_MISSION_ID = str(uuid5(_TEST_NS, "mission:intent-test"))


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    hashed = security.hash_password("test-pass")
    user = User(
        id=_INTENT_USER_ID,
        email="intent-test@test.dev",
        display_name="Intent Tester",
        hashed_password=hashed,
        system_role="user",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def mission(db_session: AsyncSession, user: User) -> Mission:
    m = Mission(
        id=_INTENT_MISSION_ID,
        name="intent-test-mission",
        description="A mission for intent tests",
        owner_id=user.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(m)
    await db_session.flush()
    return m


class TestMissionIntentService:
    @pytest.mark.asyncio
    async def test_create_first_intent(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        result = await svc.create_intent(
            mission.id,
            "Build an auth module with JWT",
            source="system",
            reason="Initial brief",
        )
        assert result is not None
        assert result.intent == "Build an auth module with JWT"
        assert result.intent_summary == "Build an auth module with JWT"
        assert result.source == "system"
        assert result.revised_from is None

    @pytest.mark.asyncio
    async def test_create_revision_links_to_previous(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        first = await svc.create_intent(
            mission.id, "Original intent",
            source="system", reason="Initial",
        )
        second = await svc.create_intent(
            mission.id, "Revised intent",
            source="user_cli", reason="Changed mind",
        )
        assert second is not None
        assert second.revised_from == first.id

    @pytest.mark.asyncio
    async def test_dedup_identical_intent(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        await svc.create_intent(
            mission.id, "Same intent",
            scope={"in": ["auth"]},
            source="system", reason="First",
        )
        duplicate = await svc.create_intent(
            mission.id, "Same intent",
            scope={"in": ["auth"]},
            source="user_cli", reason="Should dedup",
        )
        assert duplicate is None

    @pytest.mark.asyncio
    async def test_dedup_different_scope_creates_new(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        await svc.create_intent(
            mission.id, "Same text",
            scope={"in": ["auth"]},
            source="system", reason="First",
        )
        different_scope = await svc.create_intent(
            mission.id, "Same text",
            scope={"in": ["auth", "api"]},
            source="user_cli", reason="Expanded scope",
        )
        assert different_scope is not None

    @pytest.mark.asyncio
    async def test_get_current_returns_most_recent(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        await svc.create_intent(
            mission.id, "Old intent",
            source="system", reason="First",
        )
        await svc.create_intent(
            mission.id, "Current intent",
            source="user_cli", reason="Updated",
        )
        current = await svc.get_current(mission.id)
        assert current is not None
        assert current.intent == "Current intent"

    @pytest.mark.asyncio
    async def test_get_current_no_intents(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        current = await svc.get_current(mission.id)
        assert current is None

    @pytest.mark.asyncio
    async def test_list_revisions_newest_first(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        await svc.create_intent(mission.id, "First", source="system", reason="1")
        await svc.create_intent(mission.id, "Second", source="user_cli", reason="2")
        await svc.create_intent(mission.id, "Third", source="director_inferred", reason="3")

        revisions = await svc.list_revisions(mission.id)
        assert len(revisions) == 3
        assert revisions[0].intent == "Third"
        assert revisions[2].intent == "First"

    @pytest.mark.asyncio
    async def test_count_revisions(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        await svc.create_intent(mission.id, "One", source="system", reason="1")
        await svc.create_intent(mission.id, "Two", source="system", reason="2")

        count = await svc.count_revisions(mission.id)
        assert count == 2

    @pytest.mark.asyncio
    async def test_summary_truncation(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        long_intent = "x" * 500
        result = await svc.create_intent(
            mission.id, long_intent,
            source="system", reason="Long",
        )
        assert len(result.intent_summary) <= 163  # 160 + "..."

    @pytest.mark.asyncio
    async def test_summary_first_sentence(self, db_session: AsyncSession, mission: Mission):
        svc = MissionIntentService(db_session)
        result = await svc.create_intent(
            mission.id,
            "Build auth module. Then add testing. Finally deploy.",
            source="system", reason="Multi-sentence",
        )
        assert result.intent_summary == "Build auth module."
