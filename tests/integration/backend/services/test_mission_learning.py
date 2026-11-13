"""
Integration tests for MissionLearningService + MissionLearningExtractor.

Real database, no mocks (P12). Tests CRUD, idempotent evidence-derived dedup,
promote/retract, contradiction detection, and the deterministic extractor.
"""

from datetime import timedelta
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.config import get_app_config
from modules.backend.core.utils import utc_now
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
_TEX_LEARN_003 = str(uuid5(_TEST_NS, "tex:learn-003"))
_EXEC_LEARN_004 = str(uuid5(_TEST_NS, "exec:learn-004"))
_TEX_LEARN_004 = str(uuid5(_TEST_NS, "tex:learn-004"))


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
    db_session.add(
        MissionPlan(
            mission_id=m.id,
            gate_mode=GateMode.MANUAL,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
        )
    )
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


async def _failed_execution(
    db_session: AsyncSession,
    mission: Mission,
    test_session: Session,
    *,
    agent_name: str,
) -> TaskExecution:
    """A FAILED task execution with no attempts; callers add the attempts."""
    record = ExecutionRecord(
        id=_EXEC_LEARN_004,
        mission_id=mission.id,
        session_id=test_session.id,
        objective_statement="Extractor scenario",
        status=ExecutionRecordStatus.COMPLETED,
    )
    db_session.add(record)
    await db_session.flush()
    tex = TaskExecution(
        id=_TEX_LEARN_004,
        execution_record_id=record.id,
        task_id=str(uuid5(_TEST_NS, "task:learn-004")),
        agent_name=agent_name,
        status=TaskExecutionStatus.FAILED,
    )
    db_session.add(tex)
    await db_session.flush()
    return tex


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
    async def test_repeat_extraction_does_not_inflate_count(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)

        created1 = await extractor.extract_for_mission(mission.id)
        assert len(created1) == 1
        learning = created1[0]
        await db_session.refresh(learning)
        before = (learning.occurrence_count, learning.confidence, learning.updated_at)

        created2 = await extractor.extract_for_mission(mission.id)
        assert created2 == []
        await db_session.refresh(learning)
        after = (learning.occurrence_count, learning.confidence, learning.updated_at)

        assert after == before
        assert learning.occurrence_count == 3
        assert learning.evidence["failure_tiers"] == ["tier_1_structural"]

    @pytest.mark.asyncio
    async def test_new_failure_increments_count_by_exactly_one(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)
        learning = (await extractor.extract_for_mission(mission.id))[0]
        await db_session.refresh(learning)
        count_before = learning.occurrence_count

        db_session.add(
            TaskAttempt(
                task_execution_id=_TEX_LEARN_001,
                attempt_number=4,
                status=TaskAttemptStatus.FAILED,
                failure_tier="tier_1_structural",
                failure_reason="Validation failed: error 3",
            )
        )
        await db_session.flush()

        assert await extractor.extract_for_mission(mission.id) == []
        await db_session.refresh(learning)
        assert learning.occurrence_count == count_before + 1
        assert learning.confidence == pytest.approx(
            MissionLearningExtractor._compute_confidence(count_before + 1)
        )
        assert f"({count_before + 1}x)" in learning.title

        # Count 4 gives a confidence the Numeric(12, 6) column rounds; a sweep
        # over the reloaded row must still see no change.
        updated_at = learning.updated_at
        assert await extractor.extract_for_mission(mission.id) == []
        await db_session.refresh(learning)
        assert learning.updated_at == updated_at

    @pytest.mark.asyncio
    async def test_kind_flip_updates_existing_learning(
        self,
        db_session: AsyncSession,
        mission: Mission,
        execution_with_failures: ExecutionRecord,
    ):
        extractor = MissionLearningExtractor(db_session)
        learning = (await extractor.extract_for_mission(mission.id))[0]
        assert learning.kind == LearningKind.FAILURE_PATTERN.value
        failure_recommendation = learning.recommendation
        learning_id = learning.id

        db_session.add(
            TaskExecution(
                id=_TEX_LEARN_003,
                execution_record_id=execution_with_failures.id,
                task_id=str(uuid5(_TEST_NS, "task:learn-003")),
                agent_name="software.quality.agent",
                status=TaskExecutionStatus.COMPLETED,
                domain_tags=["quality"],
            )
        )
        await db_session.flush()

        assert await extractor.extract_for_mission(mission.id) == []
        await db_session.refresh(learning)
        assert learning.id == learning_id
        assert learning.kind == LearningKind.RETRY_STRATEGY.value
        assert learning.recommendation != failure_recommendation
        assert learning.recommendation == "Retry with feedback: Fix the validation"
        rows = await MissionLearningService(db_session).list_by_mission(mission.id, status=None)
        assert [r.id for r in rows] == [learning_id]

    @pytest.mark.asyncio
    async def test_two_tiers_produce_two_learnings(
        self,
        db_session: AsyncSession,
        mission: Mission,
        test_session: Session,
    ):
        tex = await _failed_execution(db_session, mission, test_session, agent_name="tiered.agent")
        for i, tier in enumerate(
            ["tier_1_structural", "tier_1_structural", "tier_2_quality", "tier_2_quality"]
        ):
            db_session.add(
                TaskAttempt(
                    task_execution_id=tex.id,
                    attempt_number=i + 1,
                    status=TaskAttemptStatus.FAILED,
                    failure_tier=tier,
                    failure_reason=f"fail {i}",
                )
            )
        await db_session.flush()

        created = await MissionLearningExtractor(db_session).extract_for_mission(mission.id)

        tiered = [c for c in created if "tiered.agent" in c.agent_names]
        assert len(tiered) == 2
        assert {tuple(c.evidence["failure_tiers"]) for c in tiered} == {
            ("tier_1_structural",),
            ("tier_2_quality",),
        }
        assert all(c.occurrence_count == 2 for c in tiered)

    @pytest.mark.asyncio
    async def test_window_excludes_old_attempts_from_creation(
        self,
        db_session: AsyncSession,
        mission: Mission,
        test_session: Session,
    ):
        window_days = get_app_config().missions.knowledge.learnings.extraction_window_days
        old = utc_now() - timedelta(days=window_days + 1)
        tex = await _failed_execution(db_session, mission, test_session, agent_name="old.agent")
        for i in range(3):
            db_session.add(
                TaskAttempt(
                    task_execution_id=tex.id,
                    attempt_number=i + 1,
                    status=TaskAttemptStatus.FAILED,
                    failure_tier="tier_1_structural",
                    failure_reason=f"old fail {i}",
                    created_at=old,
                    updated_at=old,
                )
            )
        await db_session.flush()

        created = await MissionLearningExtractor(db_session).extract_for_mission(mission.id)

        assert [c for c in created if "old.agent" in c.agent_names] == []

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
