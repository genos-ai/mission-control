"""Setup shared by the mission API integration tests: missions, team members, LLM spend."""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.human_input_request import HumanInputRequest, HumanInputRequestStatus
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.mission_plan import MissionPlan, MissionPlanStatus
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.workflow_run import WorkflowRun
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.mission_team import MissionTeamService
from modules.backend.services.token_economics import TokenEconomicsService


async def create_mission(db: AsyncSession, name: str, owner_id: str) -> Mission:
    """A mission with its owner as a member, members loaded as the real query loads them."""
    mission = Mission(
        name=name, description=name, owner_id=owner_id, status="active", default_roster="default"
    )
    db.add(mission)
    await db.flush()
    db.add(MissionMember(mission_id=mission.id, user_id=owner_id, role=MissionMemberRole.OWNER))
    await db.flush()
    await db.refresh(mission, ["members"])
    return mission


async def add_team_member(db: AsyncSession, mission: Mission, agent_name: str):
    """A new catalog agent, put on the mission's team with an initial prompt."""
    entry = await AgentCatalogService(db).create_entry(
        agent_name=agent_name,
        agent_type="vertical",
        description="Test agent",
        model_config_json={
            "name": "anthropic:claude-haiku-4-5-20251001",
            "temperature": 0.0,
            "max_tokens": 4096,
        },
    )
    return await MissionTeamService(db).add_agent(
        mission.id, str(entry.id), user_prompt="original prompt"
    )


async def record_spend(db: AsyncSession, mission: Mission, *costs: float) -> None:
    """One recorded LLM call per cost."""
    economics = TokenEconomicsService(db)
    for cost in costs:
        await economics.record_call(
            session_id=None,
            mission_id=str(mission.id),
            agent_name="research.analyst.agent",
            agent_role="task",
            model="copilot:claude-haiku-4.5",
            provider="copilot",
            input_tokens=100,
            output_tokens=10,
            cache_read_tokens=0,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            thinking_tokens=0,
            cost_usd=cost,
        )
    await db.flush()


async def create_plan(
    db: AsyncSession, mission: Mission, gate_mode: str | None, status=None
) -> MissionPlan:
    """A plan on the mission, ACTIVE unless a status is given."""
    plan = MissionPlan(
        mission_id=mission.id, gate_mode=gate_mode, status=status or MissionPlanStatus.ACTIVE
    )
    db.add(plan)
    await db.flush()
    return plan


async def create_tasks(
    db: AsyncSession, plan: MissionPlan, status: TaskStatus, count: int
) -> list[Task]:
    """`count` tasks on the plan, all in `status`."""
    tasks = [
        Task(
            mission_id=plan.mission_id,
            plan_id=plan.id,
            agent="research.analyst.agent",
            description=f"{status.value} task {i}",
            status=status,
        )
        for i in range(count)
    ]
    db.add_all(tasks)
    await db.flush()
    return tasks


async def create_gate_request(
    db: AsyncSession, mission: Mission, plan: MissionPlan, gate_type: str = "post_run"
):
    """A gate request waiting for a decision."""
    request = GateRequest(
        mission_id=mission.id,
        plan_id=plan.id,
        gate_type=gate_type,
        context_json={},
        status=GateRequestStatus.PENDING,
        created_at=utc_now(),
    )
    db.add(request)
    await db.flush()
    return request


async def create_human_input(db: AsyncSession, mission: Mission, prompt: str):
    """A workflow step waiting for a person's answer."""
    run = WorkflowRun(
        workflow_name="attention-test",
        workflow_version=1,
        mission_id=mission.id,
        triggered_by="test",
    )
    db.add(run)
    await db.flush()
    request = HumanInputRequest(
        workflow_run_id=run.id,
        step_id="ask",
        mission_id=mission.id,
        temporal_workflow_id="attention-test-workflow",
        prompt_message=prompt,
        status=HumanInputRequestStatus.PENDING,
    )
    db.add(request)
    await db.flush()
    return request
