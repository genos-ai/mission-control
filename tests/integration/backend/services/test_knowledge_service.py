"""
Integration tests for KnowledgeService.

Real database, no mocks (P12). Tests the unified facade: get_mission_knowledge,
get_current_intent, and structured search.

Semantic/hybrid search requires pgvector — those tests are marked separately.
"""

from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_context import MissionContext
from modules.backend.models.mission_learning import LearningKind
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.user import User
from modules.backend.services.knowledge import KnowledgeService
from modules.backend.services.mission_intent import MissionIntentService
from modules.backend.services.mission_learning import MissionLearningService

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_KS_USER_ID = str(uuid5(_TEST_NS, "user:ks-tester"))
_KS_MISSION_ID = str(uuid5(_TEST_NS, "mission:ks-test"))


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    hashed = security.hash_password("test-pass")
    u = User(
        id=_KS_USER_ID,
        email="ks@test.dev",
        display_name="KS Tester",
        hashed_password=hashed,
        system_role="admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
async def mission(db_session: AsyncSession, user: User) -> Mission:
    m = Mission(
        id=_KS_MISSION_ID,
        name="ks-test",
        description="Knowledge service test mission",
        owner_id=user.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(m)
    await db_session.flush()
    db_session.add(MissionPlan(mission_id=m.id, gate_mode=GateMode.MANUAL))

    # Seed MCD
    mcd = MissionContext(
        mission_id=m.id,
        context_data={
            "version": 1,
            "identity": {"name": "ks-test"},
            "architecture": {"components": {}},
            "decisions": [],
            "current_state": {},
            "guardrails": [],
        },
        version=1,
        size_characters=100,
        size_tokens=25,
    )
    db_session.add(mcd)
    await db_session.flush()
    return m


@pytest.fixture
async def seeded_knowledge(
    db_session: AsyncSession,
    mission: Mission,
) -> dict:
    """Seed intent + learnings for search tests."""
    # Intent
    intent_svc = MissionIntentService(db_session)
    intent = await intent_svc.create_intent(
        mission.id,
        "Build auth module with JWT and role-based access",
        scope={"in": ["auth", "api"], "out": ["frontend"]},
        source="system",
        reason="Initial brief",
    )

    # Learnings
    learning_svc = MissionLearningService(db_session)
    l1 = await learning_svc.create_learning(
        mission.id,
        kind=LearningKind.FAILURE_PATTERN.value,
        title="Auth agent token limit exceeded",
        body="Agent ran out of tokens during auth scan",
        recommendation="Split auth scan into sub-modules",
        domain_tags=["auth", "security"],
        agent_names=["software.quality.agent"],
        confidence=0.85,
    )
    l2 = await learning_svc.create_learning(
        mission.id,
        kind=LearningKind.RETRY_STRATEGY.value,
        title="Database migration retry with rollback",
        body="Migration fails on first try but succeeds after rollback",
        recommendation="Always rollback before retry on migration tasks",
        domain_tags=["database", "migration"],
        agent_names=["software.architecture.agent"],
        confidence=0.6,
    )

    return {"intent": intent, "learnings": [l1, l2]}


# ── get_mission_knowledge ────────────────────────────────────


class TestGetMissionKnowledge:
    @pytest.mark.asyncio
    async def test_returns_all_sections(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        result = await svc.get_mission_knowledge(mission.id)

        assert "mcd" in result
        assert "intent" in result
        assert "learnings" in result
        assert "recent_failures" in result
        assert "recent_summaries" in result

    @pytest.mark.asyncio
    async def test_mcd_present(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        result = await svc.get_mission_knowledge(mission.id)
        assert result["mcd"]["identity"]["name"] == "ks-test"

    @pytest.mark.asyncio
    async def test_intent_present(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        result = await svc.get_mission_knowledge(mission.id)
        assert result["intent"] is not None
        assert "auth" in result["intent"]["intent"].lower()

    @pytest.mark.asyncio
    async def test_learnings_present(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        result = await svc.get_mission_knowledge(mission.id)
        assert len(result["learnings"]) == 2

    @pytest.mark.asyncio
    async def test_domain_tag_filter(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        result = await svc.get_mission_knowledge(
            mission.id,
            domain_tags=["auth"],
        )
        # Only auth-tagged learning should appear
        assert len(result["learnings"]) == 1
        assert result["learnings"][0]["title"] == "Auth agent token limit exceeded"


# ── get_current_intent ───────────────────────────────────────


class TestGetCurrentIntent:
    @pytest.mark.asyncio
    async def test_returns_intent(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        intent = await svc.get_current_intent(mission.id)
        assert intent is not None
        assert "auth" in intent["intent"].lower()
        assert intent["scope"]["in"] == ["auth", "api"]

    @pytest.mark.asyncio
    async def test_no_intent(self, db_session: AsyncSession, mission: Mission):
        svc = KnowledgeService(db_session)
        intent = await svc.get_current_intent(mission.id)
        assert intent is None


# ── structured search ────────────────────────────────────────


class TestStructuredSearch:
    @pytest.mark.asyncio
    async def test_finds_by_title_substring(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        results = await svc.search(
            "token limit",
            mission_id=mission.id,
            mode="structured",
        )
        assert len(results) >= 1
        assert any("token limit" in r.title.lower() for r in results)

    @pytest.mark.asyncio
    async def test_finds_by_recommendation_substring(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        results = await svc.search(
            "rollback",
            mission_id=mission.id,
            mode="structured",
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_no_results_for_unmatched_query(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        results = await svc.search(
            "xyznonexistent",
            mission_id=mission.id,
            mode="structured",
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_kind_filter(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        results = await svc.search(
            "",
            mission_id=mission.id,
            mode="structured",
            kinds=["learning"],
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_without_mission_id(
        self,
        db_session: AsyncSession,
        mission: Mission,
        seeded_knowledge,
    ):
        svc = KnowledgeService(db_session)
        results = await svc.search(
            "auth",
            mode="structured",  # no mission_id
        )
        # Without mission_id and not platform_only, should return empty
        assert len(results) == 0
