"""
Integration tests for MissionLearningService + MissionLearningExtractor.

Real database, no mocks (P12). Tests CRUD, dedup via occurrence increment,
promote/retract, contradiction detection, and the deterministic extractor.
"""

from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_learning import LearningKind
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.session import Session
from modules.backend.models.user import User
from modules.backend.services.mission_learning import (
    MissionLearningExtractor,
    MissionLearningService,
)

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")
_LEARN_USER_ID = str(uuid5(_TEST_NS, "user:learn-tester"))
_LEARN_MISSION_ID = str(uuid5(_TEST_NS, "mission:learn-test"))
_LEARN_SESSION_ID = str(uuid5(_TEST_NS, "session:learn-test"))
_EXEC_LEARN_001 = str(uuid5(_TEST_NS, "exec:learn-001"))
_EXEC_LEARN_002 = str(uuid5(_TEST_NS, "exec:learn-002"))
_TEX_LEARN_001 = str(uuid5(_TEST_NS, "tex:learn-001"))
_TEX_LEARN_002 = str(uuid5(_TEST_NS, "tex:learn-002"))


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    hashed = security.hash_password("test-pass")
    u = User(
        id=_LEARN_USER_ID,
        email="learn@test.dev",
        display_name="Learn Tester",
        hashed_password=hashed,
        system_role="user",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
async def mission(db_session: AsyncSession, user: User) -> Mission:
    m = Mission(
        id=_LEARN_MISSION_ID,
        name="learn-test",
        description="Test mission for learnings",
        owner_id=user.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(m)
    await db_session.flush()
    db_session.add(MissionPlan(mission_id=m.id, gate_mode=GateMode.MANUAL))
    await db_session.flush()
    return m


@pytest.fixture
async def test_session(db_session: AsyncSession, mission: Mission) -> Session:
    """Create a session for execution records."""
    s = Session(
        id=_LEARN_SESSION_ID,
        mission_id=mission.id,
        user_id=_LEARN_USER_ID,
        status="active",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def execution_with_failures(
    db_session: AsyncSession,
    mission: Mission,
    test_session: Session,
) -> ExecutionRecord:
    """Create an execution record with multiple failed task attempts."""
    record = ExecutionRecord(
        id=_EXEC_LEARN_001,
        mission_id=mission.id,
        session_id=test_session.id,
        objective_statement="Run quality check",
        status=ExecutionRecordStatus.COMPLETED,
    )
    db_session.add(record)
    await db_session.flush()

    # Task execution with domain tags
    tex = TaskExecution(
        id=_TEX_LEARN_001,
        execution_record_id=record.id,
        task_id=str(uuid5(_TEST_NS, "task:learn-001")),
        agent_name="software.quality.agent",
        status=TaskExecutionStatus.FAILED,
        domain_tags=["quality", "testing"],
    )
    db_session.add(tex)
    await db_session.flush()

    # Create 3 failed attempts (>= min_occurrence of 2)
    for i in range(3):
        attempt = TaskAttempt(
            task_execution_id=tex.id,
            attempt_number=i + 1,
            status=TaskAttemptStatus.FAILED,
            failure_tier="tier_1_structural",
            failure_reason=f"Validation failed: error {i}",
            feedback_provided="Fix the validation" if i == 2 else None,
        )
        db_session.add(attempt)

    await db_session.flush()
    return record


# ── MissionLearningService ───────────────────────────────────


class TestMissionLearningService:
    @pytest.mark.asyncio
    async def test_create_learning(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        learning = await svc.create_learning(
            mission.id,
            kind=LearningKind.FAILURE_PATTERN.value,
            title="Test failure",
            body="Agent X fails on Y",
            recommendation="Use Z instead",
            domain_tags=["auth", "testing"],
            agent_names=["software.quality.agent"],
            confidence=0.7,
        )
        assert learning.id is not None
        assert learning.kind == "failure_pattern"
        assert learning.status == "active"
        assert learning.platform_promoted is False
        assert "auth" in learning.domain_tags
        assert "testing" in learning.domain_tags

    @pytest.mark.asyncio
    async def test_create_learning_validates_tags(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        learning = await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="Test",
            body="b",
            recommendation="r",
            domain_tags=["auth", "invalid_tag_xyz"],
        )
        # invalid tags are dropped, valid ones kept
        assert "auth" in learning.domain_tags
        assert "invalidtagxyz" not in learning.domain_tags

    @pytest.mark.asyncio
    async def test_list_by_mission(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="L1",
            body="b1",
            recommendation="r1",
            confidence=0.9,
        )
        await svc.create_learning(
            mission.id,
            kind="retry_strategy",
            title="L2",
            body="b2",
            recommendation="r2",
            confidence=0.5,
        )

        all_learnings = await svc.list_by_mission(mission.id)
        assert len(all_learnings) == 2

        # Filter by kind
        failures = await svc.list_by_mission(mission.id, kind="failure_pattern")
        assert len(failures) == 1
        assert failures[0].title == "L1"

    @pytest.mark.asyncio
    async def test_promote_and_list_platform(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        learning = await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="Promotable",
            body="b",
            recommendation="r",
        )

        await svc.promote(learning.id, "test-admin")
        platform = await svc.list_platform()
        assert any(x.id == learning.id for x in platform)

    @pytest.mark.asyncio
    async def test_promote_idempotent(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        learning = await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="Idempotent",
            body="b",
            recommendation="r",
        )
        await svc.promote(learning.id, "admin")
        await svc.promote(learning.id, "admin")  # no error
        platform = await svc.list_platform()
        count = sum(1 for x in platform if x.id == learning.id)
        assert count == 1

    @pytest.mark.asyncio
    async def test_retract(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        learning = await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="Retractable",
            body="b",
            recommendation="r",
        )
        await svc.retract(learning.id)

        # Retracted learnings excluded from default list
        active = await svc.list_by_mission(mission.id)
        assert not any(x.id == learning.id for x in active)

    @pytest.mark.asyncio
    async def test_find_contradiction_candidates(self, db_session: AsyncSession, mission: Mission):
        svc = MissionLearningService(db_session)
        await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="A",
            body="b",
            recommendation="Always use caching",
            domain_tags=["performance"],
            agent_names=["agent-x"],
        )
        await svc.create_learning(
            mission.id,
            kind="failure_pattern",
            title="B",
            body="b",
            recommendation="Never use caching",
            domain_tags=["performance"],
            agent_names=["agent-x"],
        )

        candidates = await svc.find_contradiction_candidates(mission.id)
        assert len(candidates) >= 1
        a, b = candidates[0]
        assert {a.title, b.title} == {"A", "B"}


# ── MissionLearningExtractor ────────────────────────────────


class TestMissionLearningExtractor:
    @pytest.mark.asyncio
    async def test_extracts_from_failures(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)
        created = await extractor.extract_for_mission(mission.id)

        assert len(created) >= 1
        learning = created[0]
        assert "software.quality.agent" in learning.agent_names
        assert learning.occurrence_count >= 2
        assert learning.confidence > 0.3

    @pytest.mark.asyncio
    async def test_no_extraction_below_threshold(
        self,
        db_session: AsyncSession,
        mission: Mission,
        test_session: Session,
    ):
        """One failure is below min_occurrence — no learning created."""
        record = ExecutionRecord(
            id=_EXEC_LEARN_002,
            mission_id=mission.id,
            session_id=test_session.id,
            objective_statement="Single fail",
            status=ExecutionRecordStatus.COMPLETED,
        )
        db_session.add(record)
        await db_session.flush()

        tex = TaskExecution(
            id=_TEX_LEARN_002,
            execution_record_id=record.id,
            task_id=str(uuid5(_TEST_NS, "task:learn-002")),
            agent_name="unique.agent",
            status=TaskExecutionStatus.FAILED,
        )
        db_session.add(tex)
        await db_session.flush()

        attempt = TaskAttempt(
            task_execution_id=tex.id,
            attempt_number=1,
            status=TaskAttemptStatus.FAILED,
            failure_reason="Single failure",
        )
        db_session.add(attempt)
        await db_session.flush()

        extractor = MissionLearningExtractor(db_session)
        created = await extractor.extract_for_mission(mission.id)

        # Should not extract — only 1 occurrence, threshold is 2
        unique_agent = [x for x in created if "unique.agent" in x.agent_names]
        assert len(unique_agent) == 0

    @pytest.mark.asyncio
    async def test_dedup_increments_occurrence(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)

        # First extraction
        created1 = await extractor.extract_for_mission(mission.id)
        assert len(created1) >= 1

        # Second extraction (same data) — should dedup
        created2 = await extractor.extract_for_mission(mission.id)
        assert len(created2) == 0  # no new learnings

    @pytest.mark.asyncio
    async def test_confidence_formula(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)
        created = await extractor.extract_for_mission(mission.id)
        learning = created[0]

        # confidence = min(0.95, 0.3 + 0.15 * count)
        expected = min(0.95, 0.3 + 0.15 * learning.occurrence_count)
        assert abs(learning.confidence - expected) < 0.01
