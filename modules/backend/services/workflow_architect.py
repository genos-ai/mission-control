"""
Workflow Architect Service.

Orchestration layer between the API/CLI and the Workflow Architect agent.
Manages design sessions, loads mission context, delegates to the agent,
and streams events back to the caller.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.deps.base import FileScope
from modules.backend.agents.mission.workflow.agent import (
    create_agent,
    run_conversational,
)
from modules.backend.agents.mission.workflow.deps import ArchitectAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.core.model_builder import _build_model
from modules.backend.core.agent_registry import get_registry
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent
from modules.backend.services.base import BaseService

logger = get_logger(__name__)

ARCHITECT_AGENT_NAME = "mission.workflow.agent"


class WorkflowArchitectService(BaseService):
    """Service for conversational workflow design sessions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["WorkflowArchitectService", None]:
        """Create a WorkflowArchitectService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield WorkflowArchitectService(db)
            await db.commit()

    async def chat(
        self,
        mission_id: str,
        message: str,
        *,
        session_id: str | None = None,
        message_history: list | None = None,
        on_event: Any = None,
    ) -> dict[str, Any]:
        """Send a message to the Workflow Architect and get a response.

        Args:
            mission_id: The mission this design session is for.
            message: User message text.
            session_id: Optional session ID for event emission.
            message_history: Prior conversation messages (PydanticAI format).
            on_event: Optional async callback for streaming events.

        Returns:
            Dict with 'response' (str), 'usage', and 'all_messages'.
        """
        mission_brief, team_summary = await self._load_mission_context(mission_id)

        deps = self._build_deps(
            mission_id=mission_id,
            mission_brief=mission_brief,
            team_summary=team_summary,
            session_id=session_id,
            on_event=on_event,
        )

        agent = self._create_agent()

        enriched_message = message
        if not message_history:
            enriched_message = self._build_initial_prompt(
                message, mission_brief, team_summary,
            )

        result = await run_conversational(
            agent, deps, enriched_message,
            message_history=message_history,
        )

        self._log_operation(
            "Architect chat completed",
            mission_id=mission_id,
            response_length=len(result.get("response", "")),
        )

        return result

    async def recommend_team(
        self,
        mission_id: str,
    ) -> list[dict[str, Any]]:
        """Recommend agents for a mission based on its brief and catalog.

        Loads the mission brief, queries the full agent catalog, constructs
        a recommendation prompt, calls the LLM, and returns a ranked list.

        Returns list of dicts with agent_name, reason, and priority.
        """
        from modules.backend.repositories.agent_catalog import AgentCatalogRepository
        from modules.backend.repositories.mission import MissionRepository

        mission_repo = MissionRepository(self._session)
        mission = await mission_repo.get_by_id(mission_id)
        mission_brief = mission.brief or mission.description or ""

        catalog_repo = AgentCatalogRepository(self._session)
        agents = await catalog_repo.list_enabled()

        if not agents:
            return []

        catalog_text = "\n".join(
            f"- {a.agent_name} ({a.agent_type}): {a.description}"
            for a in agents
        )

        prompt = (
            "You are a team composition advisor. Given a mission brief and "
            "available agents, recommend which agents should be on the team.\n\n"
            f"## Mission Brief\n\n{mission_brief}\n\n"
            f"## Available Agents\n\n{catalog_text}\n\n"
            "Respond with a JSON array of objects, each with:\n"
            '- "agent_name": the exact agent name from the catalog\n'
            '- "reason": a brief explanation of why this agent is needed\n'
            '- "priority": "high", "medium", or "low"\n\n'
            "Only include agents that are relevant to this mission. "
            "Respond with ONLY the JSON array, no other text."
        )

        agent = self._create_agent()
        deps = self._build_deps(
            mission_id=mission_id,
            mission_brief=mission_brief,
            team_summary="(requesting recommendation)",
        )

        import json
        result = await run_conversational(agent, deps, prompt)
        response_text = result.get("response", "[]")

        # Extract JSON from response (handle markdown code blocks)
        if "```" in response_text:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                response_text = response_text[start:end]

        try:
            recommendations = json.loads(response_text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse recommendation response", extra={
                "response": response_text[:200],
                "mission_id": mission_id,
            })
            recommendations = []

        self._log_operation(
            "Team recommendation generated",
            mission_id=mission_id,
            recommendation_count=len(recommendations),
        )
        return recommendations

    def _create_agent(self):
        """Create the architect agent from the registry config."""
        registry = get_registry()
        config = registry.get(ARCHITECT_AGENT_NAME)  # raises KeyError if missing
        model = _build_model(config.model)
        return create_agent(model)

    def _build_deps(
        self,
        mission_id: str,
        mission_brief: str,
        team_summary: str,
        session_id: str | None = None,
        on_event: Any = None,
    ) -> ArchitectAgentDeps:
        """Build deps for the architect agent."""
        project_root = find_project_root()
        scope = FileScope(read_paths=["config/", "modules/"], write_paths=[])

        registry = get_registry()
        config = None
        if registry.has(ARCHITECT_AGENT_NAME):
            config = registry.get(ARCHITECT_AGENT_NAME)

        return ArchitectAgentDeps(
            project_root=project_root,
            scope=scope,
            config=config,
            session_id=session_id,
            on_event=on_event,
            mission_id=mission_id,
            mission_brief=mission_brief,
            team_summary=team_summary,
            db_session=self._session,
        )

    async def _load_mission_context(
        self, mission_id: str,
    ) -> tuple[str, str]:
        """Load mission brief and team summary for the architect.

        Returns (mission_brief, team_summary) as formatted strings.
        """
        from modules.backend.repositories.agent_catalog import AgentCatalogRepository
        from modules.backend.repositories.mission import MissionRepository
        from modules.backend.services.mission_team import MissionTeamService

        mission_repo = MissionRepository(self._session)
        mission = await mission_repo.get_by_id(mission_id)

        mission_brief = mission.brief or mission.description or ""

        team_svc = MissionTeamService(self._session)
        catalog_repo = AgentCatalogRepository(self._session)

        members = await team_svc.list_team(mission_id, enabled_only=True)
        team_lines = []
        for member in members:
            entry = await catalog_repo.get_by_id_or_none(member.agent_catalog_id)
            if entry:
                team_lines.append(
                    f"- {entry.agent_name} ({entry.agent_type}): {entry.description}"
                )

        team_summary = "\n".join(team_lines) if team_lines else "No agents assigned to team yet."

        return mission_brief, team_summary

    def _build_initial_prompt(
        self,
        user_message: str,
        mission_brief: str,
        team_summary: str,
    ) -> str:
        """Build the enriched first message with mission context."""
        parts = [user_message]

        if mission_brief:
            parts.append(f"\n\n## Mission Brief\n\n{mission_brief}")

        parts.append(f"\n\n## Current Team\n\n{team_summary}")

        parts.append(
            "\n\nPlease start by browsing the agent catalog to see "
            "what capabilities are available, then propose a workflow."
        )

        return "\n".join(parts)
