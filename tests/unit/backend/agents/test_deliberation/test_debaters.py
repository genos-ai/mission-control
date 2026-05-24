"""Deliberation debater tests (Plan 79 Phase 4).

Four debaters share the same DebaterTurn output_type, BaseAgentDeps,
and create_agent shape. They differ only by:

- the debater_id Literal they must emit
- the system prompt loaded from disk

A single parametrised test covers all four to avoid 4-way duplication.
"""

from __future__ import annotations

import importlib

import pytest
import yaml
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deps.base import BaseAgentDeps, FileScope
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation import DebaterTurn


DEBATERS = [
    ("debater_systems", "deliberation.debater_systems.agent",
     "Systems Mapper", ["systems", "feedback", "second-order"]),
    ("debater_quant", "deliberation.debater_quant.agent",
     "Reductionist Quant", ["mechanism", "falsifier", "quantitative"]),
    ("debater_empiricist", "deliberation.debater_empiricist.agent",
     "Adversarial Empiricist", ["historical", "track record", "maverick"]),
    ("debater_ethicist", "deliberation.debater_ethicist.agent",
     "Distributional Ethicist", ["distribution", "absent voices", "aggregate"]),
]


@pytest.fixture
def debater_deps():
    return BaseAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
    )


@pytest.mark.parametrize("module_name,agent_name,heading,keywords", DEBATERS)
class TestDebaterAgents:
    """Plan 79 Phase 4 — Opus 4.7 debaters with shared schema, different
    prompts. The diversity is in the prompts, not the code."""

    @pytest.mark.asyncio
    async def test_run_produces_debater_turn(
        self, module_name, agent_name, heading, keywords, debater_deps,
    ):
        mod = importlib.import_module(
            f"modules.backend.agents.deliberation.{module_name}.agent",
        )
        agent = mod.create_agent(TestModel(call_tools=[]))
        result = await agent.run("Open your position.", deps=debater_deps)
        assert isinstance(result.output, DebaterTurn)

    def test_yaml_matches_agent_config_schema(
        self, module_name, agent_name, heading, keywords,
    ):
        from modules.backend.schemas.agent_config import AgentConfigSchema

        path = (
            find_project_root()
            / "config" / "agents" / "deliberation" / module_name / "agent.yaml"
        )
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = AgentConfigSchema(**raw)
        assert config.agent_name == agent_name
        # All four use Opus 4.6 per Plan 79 §6.1 (downshifted from 4.7
        # which is not yet available in the Copilot SDK).
        assert config.model.name == "copilot:claude-opus-4.6"
        # All four use the high max_input_length (sparse topology
        # round inputs can be ~5-20 KB).
        assert config.max_input_length == 100000
        # Debaters have no tools — they reason on their input.
        assert config.tools == []

    def test_prompt_loads_with_role_content(
        self, module_name, agent_name, heading, keywords,
    ):
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", module_name)
        # Heading should appear (smoke check that the right file loaded).
        assert heading in prompt
        # Each debater has its characteristic vocabulary.
        prompt_lower = prompt.lower()
        for keyword in keywords:
            assert keyword.lower() in prompt_lower, (
                f"{module_name} prompt missing keyword '{keyword}'"
            )

    def test_prompt_has_hold_concede_schema(
        self, module_name, agent_name, heading, keywords,
    ):
        # All four debater prompts must reference the four DECISION values.
        # If any drift away from this schema, the sycophancy detector breaks.
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", module_name)
        for decision in ("HOLD", "REFINE", "CONCEDE_PARTIAL", "CONCEDE_FULL"):
            assert decision in prompt, (
                f"{module_name} prompt missing decision value '{decision}'"
            )


class TestDebaterDiversity:
    """Plan 79 §3 / research §3 — the four debaters cover the four
    quadrants of (mechanism vs system) × (efficiency vs equity). Smoke
    check that their prompts are actually meaningfully different and not
    accidental copies."""

    def test_prompts_are_distinct(self):
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompts = {
            module_name: assemble_instructions("deliberation", module_name)
            for module_name, *_ in DEBATERS
        }
        # Each pair of prompts should differ substantially (>30% of chars
        # different). If two prompts are nearly identical, a copy-paste
        # error has happened.
        import difflib

        modules = list(prompts.keys())
        for i, a in enumerate(modules):
            for b in modules[i + 1:]:
                ratio = difflib.SequenceMatcher(
                    None, prompts[a], prompts[b],
                ).ratio()
                assert ratio < 0.7, (
                    f"Prompts {a} and {b} are {ratio:.0%} similar — "
                    f"likely copy-paste error"
                )

    def test_empiricist_is_explicitly_maverick(self):
        """The Adversarial Empiricist's prompt must explicitly call out
        the maverick role. Without that, the anti-collapse-to-mainstream
        machinery loses its load-bearing component."""
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "debater_empiricist")
        assert "maverick" in prompt.lower()
        assert "challenge the mainstream consensus" in prompt.lower()
