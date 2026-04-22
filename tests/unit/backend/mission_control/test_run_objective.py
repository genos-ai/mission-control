"""Tests for MissionPlanService.run_objective() — Plan 62 unified execution path.

Tests concurrency guard, gate mode handling, async/sync dispatch, budget
propagation, and approve_all_proposed. Uses real db_session per project
testing principles.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.models.mission_plan import PlanTaskStatus
from modules.backend.services.mission_plan import MissionPlanService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mission_id(db_session: AsyncSession) -> str:
    """Create a real user + mission and return the mission ID."""
    from modules.backend.models.mission import Mission
    from modules.backend.models.user import User

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        email=f"test-{uuid.uuid4().hex[:6]}@test.com",
        display_name="Test User",
        hashed_password="not-a-real-hash",
    )
    db_session.add(user)
    await db_session.flush()

    m = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for run_objective",
        owner_id=user_id,
        gate_mode="autonomous",
        budget_ceiling_usd=10.0,
    )
    db_session.add(m)
    await db_session.flush()
    return m.id


@pytest.fixture
def service(db_session: AsyncSession) -> MissionPlanService:
    return MissionPlanService(db_session)


def _mock_planning_agent_result(task_count: int = 1, plan_version: int = 1) -> dict:
    """Build a mock planning agent result with N tasks."""
    tasks = []
    for i in range(task_count):
        tasks.append({
            "task_id": f"v{plan_version}-task-{i+1:03d}",
            "agent": "system.summarization.agent",
            "agent_version": "1.0.0",
            "description": f"Test task {i+1}",
            "instructions": f"Do thing {i+1}",
            "dependencies": [f"v{plan_version}-task-{i:03d}"] if i > 0 else [],
            "verification": {
                "tier_1": {"schema_validation": False, "required_output_fields": []},
                "tier_2": {"deterministic_checks": []},
                "tier_3": {"requires_ai_evaluation": False},
            },
        })
    return {
        "task_plan": {
            "version": "1.0.0",
            "mission_id": "test",
            "summary": "Test plan",
            "estimated_cost_usd": 1.0,
            "estimated_duration_seconds": 60,
            "tasks": tasks,
        },
    }


# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------


class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_rejects_when_queued_tasks(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """ConflictError raised when plan has tasks in QUEUED state."""
        plan = await service.get_or_create_plan(mission_id)

        # Manually insert a task plan + queued state
        from modules.backend.repositories.mission_plan import MissionPlanRepository
        repo = MissionPlanRepository(db_session)
        await repo.create_task_state(plan.id, "v1-task-001")
        state = await repo.get_task_state_required(plan.id, "v1-task-001")
        state.status = PlanTaskStatus.QUEUED.value
        await db_session.flush()

        with pytest.raises(ConflictError, match="in-progress"):
            await service._check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_rejects_when_running_tasks(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """ConflictError raised when plan has tasks in RUNNING state."""
        plan = await service.get_or_create_plan(mission_id)

        from modules.backend.repositories.mission_plan import MissionPlanRepository
        repo = MissionPlanRepository(db_session)
        await repo.create_task_state(plan.id, "v1-task-001")
        state = await repo.get_task_state_required(plan.id, "v1-task-001")
        state.status = PlanTaskStatus.RUNNING.value
        await db_session.flush()

        with pytest.raises(ConflictError, match="in-progress"):
            await service._check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_allows_when_only_terminal_tasks(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """No error when all tasks are in terminal states."""
        plan = await service.get_or_create_plan(mission_id)

        from modules.backend.repositories.mission_plan import MissionPlanRepository
        repo = MissionPlanRepository(db_session)
        await repo.create_task_state(plan.id, "v1-task-001")
        state = await repo.get_task_state_required(plan.id, "v1-task-001")
        state.status = PlanTaskStatus.COMPLETED.value
        await db_session.flush()

        # Should not raise
        await service._check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_allows_empty_plan(
        self, service: MissionPlanService, mission_id: str,
    ):
        """No error when plan has no tasks at all."""
        plan = await service.get_or_create_plan(mission_id)
        await service._check_no_active_tasks(plan.id)


# ---------------------------------------------------------------------------
# approve_all_proposed
# ---------------------------------------------------------------------------


class TestApproveAllProposed:
    @pytest.mark.asyncio
    async def test_approves_all_proposed_tasks(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        plan = await service.get_or_create_plan(mission_id)

        # Create proposed tasks
        from modules.backend.repositories.mission_plan import MissionPlanRepository
        repo = MissionPlanRepository(db_session)

        # Need a task_plan_json so approve_task can walk dependencies
        plan.task_plan_json = _mock_planning_agent_result(2)["task_plan"]
        await db_session.flush()

        await repo.create_task_state(plan.id, "v1-task-001")
        await repo.create_task_state(plan.id, "v1-task-002")
        await db_session.flush()

        approved = await service.approve_all_proposed(plan.id, "test-user")

        assert len(approved) >= 2
        assert "v1-task-001" in approved
        assert "v1-task-002" in approved

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_proposed(
        self, service: MissionPlanService, mission_id: str,
    ):
        plan = await service.get_or_create_plan(mission_id)
        approved = await service.approve_all_proposed(plan.id, "test-user")
        assert approved == []


# ---------------------------------------------------------------------------
# run_objective — interactive gate mode
# ---------------------------------------------------------------------------


def _patch_planning():
    """Context manager that patches the Planning Agent and roster derivation."""
    from unittest.mock import MagicMock
    from modules.backend.agents.mission_control.roster import Roster, RosterAgentEntry, RosterConstraintsSchema, RosterInterfaceSchema, RosterModelSchema

    mock_roster = Roster(agents=[
        RosterAgentEntry(
            agent_name="system.summarization.agent",
            agent_version="1.0.0",
            description="Test agent",
            model=RosterModelSchema(name="test"),
            interface=RosterInterfaceSchema(input={}, output={}),
            constraints=RosterConstraintsSchema(timeout_seconds=60),
        ),
    ])

    return [
        patch(
            "modules.backend.services.mission_plan.MissionPlanService.refine",
        ),
        patch(
            "modules.backend.agents.mission_control.roster.derive_roster_from_team",
            new_callable=AsyncMock,
            return_value=mock_roster,
        ),
    ]


class TestRunObjectiveInteractive:
    @pytest.mark.asyncio
    async def test_interactive_stops_after_refine(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """Interactive gate mode creates plan but does not dispatch."""
        mock_result = _mock_planning_agent_result(2)

        # Mock refine to set task_plan_json directly (avoids Planning Agent + roster)
        async def mock_refine(plan_id, instructions, user_id, **kwargs):
            plan = await service._repo.get_by_id(plan_id)
            plan.task_plan_json = mock_result["task_plan"]
            plan.version += 1
            from modules.backend.repositories.mission_plan import MissionPlanRepository
            repo = MissionPlanRepository(db_session)
            for t in mock_result["task_plan"]["tasks"]:
                await repo.create_task_state(plan.id, t["task_id"])
            await db_session.flush()
            return plan

        with patch.object(service, "refine", side_effect=mock_refine):
            result = await service.run_objective(
                mission_id=mission_id,
                objective="Test objective",
                user_id="test-user",
                gate_mode="interactive",
            )

        assert result["outcome_status"] == "awaiting_approval"
        assert result["task_count"] == 2
        assert result["dispatched_task_ids"] == []
        assert result["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# run_objective — async dispatch
# ---------------------------------------------------------------------------


class TestRunObjectiveAsync:
    @pytest.mark.asyncio
    async def test_async_dispatch_returns_dispatching(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """async_dispatch=True approves tasks and returns without dispatching."""
        mock_result = _mock_planning_agent_result(1)

        async def mock_refine(plan_id, instructions, user_id, **kwargs):
            plan = await service._repo.get_by_id(plan_id)
            plan.task_plan_json = mock_result["task_plan"]
            plan.version += 1
            from modules.backend.repositories.mission_plan import MissionPlanRepository
            repo = MissionPlanRepository(db_session)
            for t in mock_result["task_plan"]["tasks"]:
                await repo.create_task_state(plan.id, t["task_id"])
            await db_session.flush()
            return plan

        with patch.object(service, "refine", side_effect=mock_refine):
            result = await service.run_objective(
                mission_id=mission_id,
                objective="Quick task",
                user_id="test-user",
                async_dispatch=True,
            )

        assert result["outcome_status"] == "dispatching"
        assert len(result["dispatched_task_ids"]) == 1
        assert result["plan_id"] is not None


# ---------------------------------------------------------------------------
# run_objective — budget propagation
# ---------------------------------------------------------------------------


class TestRunObjectiveBudget:
    @pytest.mark.asyncio
    async def test_budget_inherited_from_mission(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """Budget ceiling propagates from mission to plan."""
        plan = await service.get_or_create_plan(mission_id)
        assert plan.budget_usd_ceiling == 10.0  # inherited from fixture

    @pytest.mark.asyncio
    async def test_budget_override(
        self, service: MissionPlanService, mission_id: str, db_session: AsyncSession,
    ):
        """Explicit budget_ceiling_usd overrides mission default."""
        mock_result = _mock_planning_agent_result(1)

        async def mock_refine(plan_id, instructions, user_id, **kwargs):
            plan = await service._repo.get_by_id(plan_id)
            plan.task_plan_json = mock_result["task_plan"]
            plan.version += 1
            from modules.backend.repositories.mission_plan import MissionPlanRepository
            repo = MissionPlanRepository(db_session)
            for t in mock_result["task_plan"]["tasks"]:
                await repo.create_task_state(plan.id, t["task_id"])
            await db_session.flush()
            return plan

        with patch.object(service, "refine", side_effect=mock_refine):
            result = await service.run_objective(
                mission_id=mission_id,
                objective="Budget test",
                user_id="test-user",
                budget_ceiling_usd=25.0,
                async_dispatch=True,
            )

        # Verify plan has the overridden budget
        plan = await service.get_or_create_plan(mission_id)
        assert plan.budget_usd_ceiling == 25.0
