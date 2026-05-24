"""
Advocate-Judge Framings Validator agent tests (Plan 80 Phase 2).

Pattern mirrors test_research_verifier.py. TestModel auto-generates
schema-valid responses so we exercise wiring without real LLM calls.

The validator is the P13 separate-agent audit on the framer's output:
either approves or replaces the CandidateSet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deliberation.advocate_judge_framings_validator.agent import (
    create_agent,
)
from modules.backend.agents.deps.base import BaseAgentDeps, FileScope
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation_advocate_judge import FramingValidation


@pytest.fixture
def validator_deps():
    return BaseAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
    )


class TestAdvocateJudgeFramingsValidator:
    """Audits the framer's CandidateSet for hidden bias and missing schools."""

    @pytest.mark.asyncio
    async def test_creates_agent(self):
        agent = create_agent(TestModel(call_tools=[]))
        assert agent is not None

    @pytest.mark.asyncio
    async def test_run_produces_framing_validation(self, validator_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run(
            "Audit this CandidateSet.", deps=validator_deps,
        )
        assert isinstance(result.output, FramingValidation)
        # Schema enforces verdict in {approved, revised}.
        assert result.output.verdict in {"approved", "revised"}
        # revised_set invariant: present iff verdict=='revised' (enforced
        # by the schema validator).
        if result.output.verdict == "revised":
            assert result.output.revised_set is not None
        else:
            assert result.output.revised_set is None

    @pytest.mark.asyncio
    async def test_rationale_is_non_empty(self, validator_deps):
        agent = create_agent(TestModel(call_tools=[]))
        result = await agent.run("Audit.", deps=validator_deps)
        assert result.output.rationale
        assert isinstance(result.output.rationale, str)

    def test_instructions_loaded_from_disk(self):
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions(
            "deliberation", "advocate_judge_framings_validator",
        )
        assert "Framings Validator" in prompt or "Framings validator" in prompt
        assert "audit" in prompt.lower()
        # The five failure modes the validator MUST check (direction
        # bias, missing school, strawman, softened mainstream, overlap)
        # are the validator's contract.
        assert "bias" in prompt.lower()
        assert "missing" in prompt.lower()
        assert "strawman" in prompt.lower()
        assert "mainstream" in prompt.lower()

    def test_yaml_declares_no_tools(self):
        """The framings validator is pure reasoning — no web access."""
        import yaml

        yaml_path = (
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framings_validator/agent.yaml"
        )
        config = yaml.safe_load(yaml_path.read_text())
        assert config["tools"] == []

    def test_yaml_uses_different_model_family_from_framer(self):
        """Per Plan 80 §5.1: the validator should default to a different
        model family from the framer, so the audit catches family-specific
        priors. Framer defaults to Claude; validator defaults to GPT."""
        import yaml

        framer_yaml = yaml.safe_load((
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framer/agent.yaml"
        ).read_text())
        validator_yaml = yaml.safe_load((
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framings_validator/agent.yaml"
        ).read_text())

        framer_model = framer_yaml["model"]["name"].lower()
        validator_model = validator_yaml["model"]["name"].lower()

        # Different families. Heuristic: framer has "claude" and validator
        # has "gpt" (or vice versa). If both happen to be the same family
        # in a future config change, this catches the regression.
        framer_is_claude = "claude" in framer_model
        validator_is_claude = "claude" in validator_model
        assert framer_is_claude != validator_is_claude, (
            f"Framer ({framer_model}) and validator ({validator_model}) "
            "use the same model family — defeats the P13 cross-family audit. "
            "See Plan 80 §5.1."
        )

    def test_yaml_declares_correct_agent_name(self):
        import yaml

        yaml_path = (
            Path(find_project_root())
            / "config/agents/deliberation/advocate_judge_framings_validator/agent.yaml"
        )
        config = yaml.safe_load(yaml_path.read_text())
        assert (
            config["agent_name"]
            == "deliberation.advocate_judge_framings_validator.agent"
        )
