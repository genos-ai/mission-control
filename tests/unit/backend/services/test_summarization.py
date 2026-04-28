"""Tests for SummarizationService.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.models.mission import Mission
from modules.backend.models.mission_history import (
    DecisionStatus,
    MissionDecision,
    MilestoneSummary,
)
from modules.backend.models.session import Session
from modules.backend.repositories.mission_history import (
    MissionDecisionRepository,
    MilestoneSummaryRepository,
)
from modules.backend.services.mission_context import (
    MissionContextManager,
    _cache,
)
from modules.backend.services.summarization import SummarizationService
from uuid import uuid5, UUID
from tests.conftest import TEST_USER_ID

_NS = UUID("00000000-0000-0000-0000-000000000000")
_MID = lambda tag: str(uuid5(_NS, f"mission:summ-{tag}"))
_NIL_UUID = "00000000-0000-0000-0000-000000000000"
_SESS_SUMM = "5714117c-eaed-5ce3-9c56-73949f03aa3d"

# All mission_id slugs used in this file — parent Mission rows are needed for FK.
_MISSION_SLUGS = [
    "proj-no-dec", "proj-prune", "proj-recent", "proj-few", "proj-mile",
    "proj-full", "proj-smr", "proj-recent-m", "proj-already",
    "proj-failed-m", "proj-tags-m", "proj-repo", "proj-sup", "proj-ms",
    "proj-other", "proj-lim",
]


@pytest.fixture
def manager(db_session: AsyncSession) -> MissionContextManager:
    return MissionContextManager(db_session)


@pytest.fixture
def summarization_service(db_session: AsyncSession) -> SummarizationService:
    return SummarizationService(db_session)


@pytest.fixture
def decision_repo(db_session: AsyncSession) -> MissionDecisionRepository:
    return MissionDecisionRepository(db_session)


@pytest.fixture
def milestone_repo(db_session: AsyncSession) -> MilestoneSummaryRepository:
    return MilestoneSummaryRepository(db_session)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear PCD cache between tests."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Session + Mission rows that child tables FK to."""
    db_session.add(Session(id=_SESS_SUMM, status="ACTIVE"))
    for slug in _MISSION_SLUGS:
        db_session.add(
            Mission(id=_MID(slug), name=slug, description="test", owner_id=TEST_USER_ID)
        )
    await db_session.flush()


class TestPrunePcdDecisions:
    @pytest.mark.asyncio
    async def test_no_pcd_returns_zero(self, summarization_service):
        """Returns 0 when project has no PCD."""
        result = await summarization_service.prune_mcd_decisions(_NIL_UUID)
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_decisions_returns_zero(
        self, summarization_service, manager,
    ):
        """Returns 0 when PCD has no decisions section."""
        await manager.create_context(_MID("proj-no-dec"), "test", "desc")
        result = await summarization_service.prune_mcd_decisions(_MID("proj-no-dec"))
        assert result == 0

    @pytest.mark.asyncio
    async def test_archives_old_decisions(
        self, summarization_service, manager, decision_repo,
    ):
        """Old decisions are archived to project_decisions table."""
        await manager.create_context(_MID("proj-prune"), "test", "desc")

        # Add decisions to PCD — mix of old and recent
        decisions = [
            {
                "id": "d1", "domain": "api", "decision": "Use REST",
                "rationale": "Standard", "made_by": "architect",
                "date": "2020-01-01",
            },
            {
                "id": "d2", "domain": "auth", "decision": "Use JWT",
                "rationale": "Stateless", "made_by": "architect",
                "date": "2020-06-01",
            },
            {
                "id": "d3", "domain": "db", "decision": "Use PostgreSQL",
                "rationale": "ACID", "made_by": "architect",
                "date": "2099-01-01",  # far future — should be kept
            },
        ]
        await manager.apply_updates(
            _MID("proj-prune"),
            [{"op": "add", "path": "decisions", "value": decisions,
              "reason": "seed decisions"}],
            agent_id="test",
        )

        result = await summarization_service.prune_mcd_decisions(
            _MID("proj-prune"), max_age_days=90,
        )
        assert result == 2  # d1 and d2 archived

        # Verify archived in DB
        archived = await decision_repo.list_active(_MID("proj-prune"))
        assert len(archived) == 2
        domains = {d.domain for d in archived}
        assert domains == {"api", "auth"}

        # Verify PCD only has the recent decision
        data = await manager.get_context(_MID("proj-prune"))
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["id"] == "d3"

    @pytest.mark.asyncio
    async def test_all_recent_decisions_kept(
        self, summarization_service, manager,
    ):
        """All recent decisions stay in PCD, nothing archived."""
        await manager.create_context(_MID("proj-recent"), "test", "desc")

        decisions = [
            {
                "id": "d1", "domain": "api", "decision": "Use REST",
                "rationale": "Standard", "made_by": "architect",
                "date": "2099-01-01",
            },
        ]
        await manager.apply_updates(
            _MID("proj-recent"),
            [{"op": "add", "path": "decisions", "value": decisions,
              "reason": "seed"}],
            agent_id="test",
        )

        result = await summarization_service.prune_mcd_decisions(_MID("proj-recent"))
        assert result == 0


class TestPruneCompletedWorkstreams:
    @pytest.mark.asyncio
    async def test_no_pcd_returns_zero(self, summarization_service):
        result = await summarization_service.prune_completed_workstreams(
            _NIL_UUID,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_few_milestones_not_pruned(
        self, summarization_service, manager,
    ):
        """5 or fewer milestones are not pruned."""
        await manager.create_context(_MID("proj-few"), "test", "desc")
        await manager.apply_updates(
            _MID("proj-few"),
            [{"op": "add", "path": "current_state",
              "value": {"recent_milestones": ["m1", "m2", "m3"]},
              "reason": "seed"}],
            agent_id="test",
        )

        result = await summarization_service.prune_completed_workstreams(
            _MID("proj-few"),
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_archives_excess_milestones(
        self, summarization_service, manager, milestone_repo,
    ):
        """Milestones beyond keep_recent are archived."""
        await manager.create_context(_MID("proj-mile"), "test", "desc")
        milestones = [f"milestone-{i}" for i in range(8)]
        await manager.apply_updates(
            _MID("proj-mile"),
            [{"op": "add", "path": "current_state",
              "value": {"recent_milestones": milestones},
              "reason": "seed"}],
            agent_id="test",
        )

        result = await summarization_service.prune_completed_workstreams(
            _MID("proj-mile"),
        )
        assert result == 3  # 8 - 5 = 3 archived

        # Verify milestone summary created
        summaries = await milestone_repo.list_by_mission(_MID("proj-mile"))
        assert len(summaries) == 1
        assert "3 items" in summaries[0].title
        assert len(summaries[0].key_outcomes["milestones"]) == 3

        # Verify PCD has only 5 milestones
        data = await manager.get_context(_MID("proj-mile"))
        assert len(data["current_state"]["recent_milestones"]) == 5


class TestRunFullPipeline:
    @pytest.mark.asyncio
    async def test_runs_both_operations(
        self, summarization_service, manager,
    ):
        """Full pipeline runs both decision and milestone pruning."""
        await manager.create_context(_MID("proj-full"), "test", "desc")

        # Add old decisions and excess milestones
        await manager.apply_updates(
            _MID("proj-full"),
            [
                {"op": "add", "path": "decisions", "value": [
                    {"id": "d1", "domain": "api", "decision": "x",
                     "rationale": "y", "made_by": "z", "date": "2020-01-01"},
                ], "reason": "seed"},
                {"op": "add", "path": "current_state", "value": {
                    "recent_milestones": [f"m{i}" for i in range(7)],
                }, "reason": "seed"},
            ],
            agent_id="test",
        )

        results = await summarization_service.run_full_pipeline(_MID("proj-full"))
        assert results["decisions_archived"] == 1
        assert results["missions_summarized"] == 0
        assert results["milestones_archived"] == 2

    @pytest.mark.asyncio
    async def test_pipeline_on_empty_project(self, summarization_service):
        """Pipeline on nonexistent project returns zeros."""
        results = await summarization_service.run_full_pipeline(_NIL_UUID)
        assert results == {
            "decisions_archived": 0,
            "missions_summarized": 0,
            "milestones_archived": 0,
        }


async def _create_old_mission(
    db: AsyncSession,
    mission_id: str,
    objective: str = "Test mission",
    cost: float = 0.5,
    completed_at: str = "2020-01-01T00:00:00Z",
    status: ExecutionRecordStatus = ExecutionRecordStatus.COMPLETED,
) -> ExecutionRecord:
    """Helper to create an old ExecutionRecord for summarization tests."""
    record = ExecutionRecord(
        session_id="5714117c-eaed-5ce3-9c56-73949f03aa3d",
        mission_id=mission_id,
        status=status,
        objective_statement=objective,
        total_cost_usd=cost,
        started_at="2020-01-01T00:00:00Z",
        completed_at=completed_at,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


class TestSummarizeMissionRecords:
    @pytest.mark.asyncio
    async def test_no_missions_returns_zero(self, summarization_service):
        """Returns 0 when no old missions exist."""
        result = await summarization_service.summarize_execution_records(
            _NIL_UUID,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_summarizes_old_missions(
        self, summarization_service, milestone_repo, db_session,
    ):
        """Old completed missions are compressed into milestone summaries."""
        m1 = await _create_old_mission(
            db_session, _MID("proj-smr"), objective="Build API",
            cost=1.0, completed_at="2020-01-01T00:00:00Z",
        )
        m2 = await _create_old_mission(
            db_session, _MID("proj-smr"), objective="Fix auth",
            cost=0.5, completed_at="2020-02-01T00:00:00Z",
        )

        result = await summarization_service.summarize_execution_records(
            _MID("proj-smr"), max_age_days=30,
        )
        assert result == 2

        # Verify milestone summary created
        milestones = await milestone_repo.list_by_mission(_MID("proj-smr"))
        assert len(milestones) == 1
        assert "2 executions" in milestones[0].title
        assert milestones[0].key_outcomes["completed"] == 2

        # Verify missions marked as summarized
        await db_session.refresh(m1)
        await db_session.refresh(m2)
        assert m1.summarized is True
        assert m2.summarized is True

    @pytest.mark.asyncio
    async def test_skips_recent_missions(
        self, summarization_service, db_session,
    ):
        """Missions newer than max_age_days are not summarized."""
        # Far future date — should not be summarized
        await _create_old_mission(
            db_session, _MID("proj-recent-m"),
            completed_at="2099-01-01T00:00:00Z",
        )

        result = await summarization_service.summarize_execution_records(
            _MID("proj-recent-m"),
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_skips_already_summarized(
        self, summarization_service, db_session,
    ):
        """Already-summarized missions are not re-summarized."""
        m = await _create_old_mission(db_session, _MID("proj-already"))
        m.summarized = True
        await db_session.flush()

        result = await summarization_service.summarize_execution_records(
            _MID("proj-already"),
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_includes_failed_missions(
        self, summarization_service, milestone_repo, db_session,
    ):
        """Failed missions are also summarized."""
        await _create_old_mission(
            db_session, _MID("proj-failed-m"),
            status=ExecutionRecordStatus.FAILED,
        )

        result = await summarization_service.summarize_execution_records(
            _MID("proj-failed-m"),
        )
        assert result == 1

        milestones = await milestone_repo.list_by_mission(_MID("proj-failed-m"))
        assert milestones[0].key_outcomes["failed"] == 1

    @pytest.mark.asyncio
    async def test_collects_domain_tags_from_executions(
        self, summarization_service, milestone_repo, db_session,
    ):
        """Domain tags from task executions are included in milestone."""
        m = await _create_old_mission(db_session, _MID("proj-tags-m"))
        te = TaskExecution(
            execution_record_id=m.id,
            task_id="t1",
            agent_name="analyzer",
            status=TaskExecutionStatus.COMPLETED,
            domain_tags=["api", "auth"],
            cost_usd=0.1,
        )
        db_session.add(te)
        await db_session.flush()

        result = await summarization_service.summarize_execution_records(
            _MID("proj-tags-m"),
        )
        assert result == 1

        milestones = await milestone_repo.list_by_mission(_MID("proj-tags-m"))
        assert "api" in milestones[0].domain_tags
        assert "auth" in milestones[0].domain_tags


class TestMissionDecisionRepository:
    @pytest.mark.asyncio
    async def test_list_by_domain(self, decision_repo, db_session):
        """Filters decisions by domain."""
        for domain in ["api", "api", "auth"]:
            await decision_repo.create(
                mission_id=_MID("proj-repo"),
                decision_id=f"d-{domain}",
                domain=domain,
                decision="test",
                rationale="test",
                made_by="test",
                status=DecisionStatus.ACTIVE,
            )

        api_decisions = await decision_repo.list_by_domain(_MID("proj-repo"), "api")
        assert len(api_decisions) == 2

        auth_decisions = await decision_repo.list_by_domain(_MID("proj-repo"), "auth")
        assert len(auth_decisions) == 1

    @pytest.mark.asyncio
    async def test_list_active_excludes_superseded(
        self, decision_repo, db_session,
    ):
        """Only active decisions are returned."""
        await decision_repo.create(
            mission_id=_MID("proj-sup"),
            decision_id="d-active",
            domain="api",
            decision="active",
            rationale="test",
            made_by="test",
            status=DecisionStatus.ACTIVE,
        )
        await decision_repo.create(
            mission_id=_MID("proj-sup"),
            decision_id="d-old",
            domain="api",
            decision="superseded",
            rationale="test",
            made_by="test",
            status=DecisionStatus.SUPERSEDED,
        )

        active = await decision_repo.list_active(_MID("proj-sup"))
        assert len(active) == 1
        assert active[0].decision_id == "d-active"


class TestMilestoneSummaryRepository:
    @pytest.mark.asyncio
    async def test_list_by_mission(self, milestone_repo, db_session):
        """Returns milestones for a specific project."""
        await milestone_repo.create(
            mission_id=_MID("proj-ms"),
            title="Phase 1",
            summary="Completed auth",
            mission_ids=["m1"],
            key_outcomes={"done": True},
            domain_tags=["auth"],
            period_end="2025-01-01",
        )
        await milestone_repo.create(
            mission_id=_MID("proj-ms"),
            title="Phase 2",
            summary="Completed API",
            mission_ids=["m2"],
            key_outcomes={"done": True},
            domain_tags=["api"],
            period_end="2025-02-01",
        )
        await milestone_repo.create(
            mission_id=_MID("proj-other"),
            title="Other",
            summary="Other project",
            mission_ids=[],
            key_outcomes={},
            domain_tags=[],
            period_end="2025-03-01",
        )

        results = await milestone_repo.list_by_mission(_MID("proj-ms"))
        assert len(results) == 2
        titles = {m.title for m in results}
        assert titles == {"Phase 1", "Phase 2"}

    @pytest.mark.asyncio
    async def test_respects_limit(self, milestone_repo, db_session):
        for i in range(5):
            await milestone_repo.create(
                mission_id=_MID("proj-lim"),
                title=f"Phase {i}",
                summary=f"Summary {i}",
                mission_ids=[],
                key_outcomes={},
                domain_tags=[],
                period_end=f"2025-0{i+1}-01",
            )

        results = await milestone_repo.list_by_mission(_MID("proj-lim"), limit=2)
        assert len(results) == 2
