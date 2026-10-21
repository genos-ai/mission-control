"""Setup shared by the mission API integration tests: missions, team members, LLM spend."""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
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
