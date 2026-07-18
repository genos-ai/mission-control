"""Research Verifier Agent tests (Plan 79 Phase 2).

Tests the agent's structured output schema and basic wiring.
No real API calls — uses PydanticAI's TestModel which auto-generates
schema-valid responses for the agent's output_type.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deliberation.research_verifier.agent import create_agent
from modules.backend.agents.deps.base import BaseAgentDeps, FileScope
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation import ResearchPacketVerification


@pytest.fixture
def verifier_deps():
    return BaseAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
    )


class TestResearchVerifierAgent:
    """Plan 79 §6 — the verifier is a cheap Haiku check between the
    Researcher and the blind opening. P13 compliance: a separate agent
    audits the packet so the Researcher does not self-evaluate."""

    @pytest.mark.asyncio
    async def test_creates_agent_with_verification_output_type(self):
        agent = create_agent(TestModel(call_tools=[]))
        # Smoke: schema-bound output. We don't introspect output_type
        # because PydanticAI may not expose it as a public attribute.
        # The agent.run below proves it.
        assert agent is not None

    @pytest.mark.asyncio
    async def test_run_produces_verification_object(self, verifier_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run(
            "Verify this packet: {'question_restated': '...'}",
            deps=verifier_deps,
        )
        assert isinstance(result.output, ResearchPacketVerification)
        # All required fields present.
        assert hasattr(result.output, "passed")
        assert hasattr(result.output, "issues")
        assert hasattr(result.output, "issues_text")
        assert hasattr(result.output, "mainstream_consensus_looks_plausible")
        assert hasattr(result.output, "under_discussed_angles_actually_under_discussed")

    @pytest.mark.asyncio
    async def test_passed_field_is_bool(self, verifier_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run("Verify the packet.", deps=verifier_deps)
        assert isinstance(result.output.passed, bool)

    @pytest.mark.asyncio
    async def test_issues_is_list_of_strings(self, verifier_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run("Verify.", deps=verifier_deps)
        assert isinstance(result.output.issues, list)
        for item in result.output.issues:
            assert isinstance(item, str)

    @pytest.mark.asyncio
    async def test_instructions_loaded_from_disk(self, verifier_deps):
        # The verifier prompt lives at:
        # config/prompts/agents/deliberation/research_verifier/system.md
        # If the prompt file is missing or unreadable, assemble_instructions
        # falls back to an empty string and the agent still constructs —
        # but its system prompt has no content. Catch that.
        from modules.backend.agents.mission_control.helpers import assemble_instructions

        prompt = assemble_instructions("deliberation", "research_verifier")
        # The prompt file should contain the verifier's checks. Smoke check
        # for content we know is in the prompt.
        assert "Verifier" in prompt or "verifier" in prompt
        assert "audit" in prompt.lower()
        # The four-check structure is the verifier's contract.
        assert "mainstream consensus" in prompt.lower() or "Mainstream consensus" in prompt
