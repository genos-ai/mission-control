"""Deliberation Researcher Agent tests (Plan 79 Phase 3).

Tests the agent's structured output schema, instructions loading, and
tool wiring. No real API or HTTP calls — TestModel auto-generates
schema-valid responses; tools are registered but not exercised.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deliberation.researcher.agent import create_agent
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation import ResearchPacket


@pytest.fixture
def researcher_deps():
    from modules.backend.agents.deps.base import FileScope

    return ResearchAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
        http_client=None,
    )


class TestResearcherAgent:
    """Plan 79 Phase 3 — researcher is Sonnet 4.6 with web search tools.
    Produces a ResearchPacket that the verifier audits before the
    debaters see it."""

    @pytest.mark.asyncio
    async def test_run_produces_research_packet(self, researcher_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run(
            "Will agentic AI displace knowledge work by 2030?",
            deps=researcher_deps,
        )
        assert isinstance(result.output, ResearchPacket)

    @pytest.mark.asyncio
    async def test_packet_has_required_sections(self, researcher_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run("Q?", deps=researcher_deps)
        # All required fields present.
        assert hasattr(result.output, "question_restated")
        assert hasattr(result.output, "what_is_known")
        assert hasattr(result.output, "expert_disagreements")
        assert hasattr(result.output, "mainstream_consensus")
        assert hasattr(result.output, "under_discussed_angles")
        assert hasattr(result.output, "base_rates")

    @pytest.mark.asyncio
    async def test_tool_names_can_be_registered(self, researcher_deps):
        # Smoke: passing tool_names doesn't crash the constructor.
        # The actual tool execution happens at run time via PydanticAI.
        agent = create_agent(
            TestModel(call_tools=[]),
            tool_names=["search_web", "fetch_url", "query_knowledge"],
        )
        result = await agent.run("Q", deps=researcher_deps)
        assert isinstance(result.output, ResearchPacket)

    def test_yaml_matches_agent_config_schema(self):
        # Catch drift between yaml and AgentConfigSchema at test time.
        from modules.backend.schemas.agent_config import AgentConfigSchema

        path = find_project_root() / "config" / "agents" / "deliberation" / "researcher" / "agent.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = AgentConfigSchema(**raw)
        assert config.agent_name == "deliberation.researcher.agent"
        assert config.model.name == "copilot:claude-sonnet-4.6"
        assert config.max_input_length == 20000
        # The researcher MUST declare its tools so the agent_executor
        # injects them. Empty tools = no search = bad packet = halted run.
        assert "search_web" in config.tools
        assert "fetch_url" in config.tools
        assert "query_knowledge" in config.tools

    def test_instructions_loaded_from_disk(self):
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "researcher")
        # Smoke check for content we know is in the prompt.
        assert "Researcher" in prompt
        assert "evidence packet" in prompt.lower()
        # The five required sections.
        assert "what is actually known" in prompt.lower()
        assert "mainstream consensus" in prompt.lower()
        assert "under-discussed" in prompt.lower()
        assert "base rates" in prompt.lower()
        # The verifier note that warns about fabricated sources.
        assert "verifier" in prompt.lower()
        assert "fabricated" in prompt.lower()
