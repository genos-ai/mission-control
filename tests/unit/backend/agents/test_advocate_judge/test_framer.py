"""
Advocate-Judge Framer agent tests (Plan 80 Phase 2).

Pattern mirrors tests/unit/backend/agents/test_deliberation/test_research_verifier.py:
TestModel auto-generates schema-valid responses for the agent's
output_type, so we exercise the wiring without real LLM calls.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deliberation.advocate_judge_framer.agent import (
    create_agent,
)
from modules.backend.agents.deps.base import FileScope
from modules.backend.agents.research.deps import ResearchAgentDeps
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation_advocate_judge import CandidateSet


@pytest.fixture
def framer_deps():
    return ResearchAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=["*"], write_paths=[]),
        http_client=None,  # Tools aren't called under TestModel.
    )


# Valid CandidateSet args passed to TestModel — bypasses TestModel's
# auto-generated strings which don't satisfy the kebab-case label
# validator on CandidateAnswer.
_VALID_CANDIDATE_SET_ARGS = {
    "candidates": [
        {
            "label": "institutional-friction",
            "statement": "Adoption lag dominates aggregate effect by 2030.",
            "rationale_for_inclusion": "Held by Solow-Paradox / Acemoglu school.",
        },
        {
            "label": "displacement-wave",
            "statement": "Headcount in routine cognitive work falls 10-20% below trend.",
            "rationale_for_inclusion": "Held by Goldman Sachs / IPPR forecast camps.",
        },
        {
            "label": "augmentation-and-growth",
            "statement": "Net employment rises as AI complements knowledge workers.",
            "rationale_for_inclusion": "Held by TBI / WEF augmentation camps.",
        },
    ],
    "mainstream_consensus": (
        "AI will disrupt knowledge work but net-create jobs through "
        "complementary roles and economic growth."
    ),
}


class TestAdvocateJudgeFramer:
    """The framer decomposes a contested question into 3-5 candidate
    answers (the live answer space) plus the mainstream consensus."""

    @pytest.mark.asyncio
    async def test_creates_agent(self):
        agent = create_agent(TestModel(call_tools=[]))
        assert agent is not None

    @pytest.mark.asyncio
    async def test_run_produces_candidate_set(self, framer_deps):
        agent = create_agent(TestModel(
            call_tools=[],
            custom_output_args=_VALID_CANDIDATE_SET_ARGS,
        ))
        result = await agent.run(
            "Decompose: Will agentic AI reduce UK knowledge-work "
            "employment by 2030?",
            deps=framer_deps,
        )
        assert isinstance(result.output, CandidateSet)
        # Schema enforces 3-5 candidates.
        assert 3 <= len(result.output.candidates) <= 5
        assert result.output.mainstream_consensus

    @pytest.mark.asyncio
    async def test_candidates_have_required_fields(self, framer_deps):
        agent = create_agent(TestModel(
            call_tools=[],
            custom_output_args=_VALID_CANDIDATE_SET_ARGS,
        ))
        result = await agent.run("Decompose the question.", deps=framer_deps)
        for c in result.output.candidates:
            assert c.label
            assert c.statement
            assert c.rationale_for_inclusion
            # Label must be kebab-case (schema validator).
            assert all(ch.islower() or ch.isdigit() or ch == "-" for ch in c.label)

    @pytest.mark.asyncio
    async def test_candidate_labels_are_unique(self, framer_deps):
        agent = create_agent(TestModel(
            call_tools=[],
            custom_output_args=_VALID_CANDIDATE_SET_ARGS,
        ))
        result = await agent.run("Decompose.", deps=framer_deps)
        labels = [c.label for c in result.output.candidates]
        assert len(labels) == len(set(labels))

    def test_instructions_loaded_from_disk(self):
        """The framer prompt lives at
        config/prompts/agents/deliberation/advocate_judge_framer/system.md.
        Catch silent-empty-prompt regressions."""
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "advocate_judge_framer")
        # Smoke check for content we know is in the prompt.
        assert "Framer" in prompt
        assert "live answer space" in prompt.lower()
        assert "candidate" in prompt.lower()
        assert "mainstream_consensus" in prompt
        # Must mention the kebab-case label constraint — the schema
        # rejects bad labels and the prompt needs to tell the model.
        assert "kebab" in prompt.lower()

    def test_yaml_declares_search_web_and_fetch_url(self):
        """The framer YAML should declare its tools.
        Phase 6 wiring registers them on the agent at dispatch time."""
        import yaml

        yaml_path = (
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framer/agent.yaml"
        )
        config = yaml.safe_load(yaml_path.read_text())
        assert "search_web" in config["tools"]
        assert "fetch_url" in config["tools"]

    def test_yaml_declares_correct_agent_name(self):
        """The YAML agent_name must match what the executor dispatches."""
        import yaml

        yaml_path = (
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framer/agent.yaml"
        )
        config = yaml.safe_load(yaml_path.read_text())
        assert config["agent_name"] == "deliberation.advocate_judge_framer.agent"
