"""Deliberation Critic Agent tests (Plan 79 Phase 5).

The critic produces a CriticReport with a 4-key `attacks` dict
constrained by a field_validator. TestModel's auto-generated output
may not always satisfy that validator (it tends to produce a single
dict entry), so we use FunctionModel to deterministically return a
valid CriticReport when we need the run to succeed.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from modules.backend.agents.deliberation.critic.agent import create_agent
from modules.backend.agents.deps.base import BaseAgentDeps, FileScope
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation import CriticReport


@pytest.fixture
def critic_deps():
    return BaseAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
    )


def _make_critic_function_model():
    """A FunctionModel that returns a schema-valid 4-key CriticReport.

    The critic uses PydanticAI's tool-call-based structured output, so
    we need to return a function-call message that triggers the
    final_result tool with our payload.
    """
    import json

    payload = {
        "round_index": 0,
        "attacks": {
            "systems": {
                "load_bearing_assumption": "A1",
                "attack": "B1",
                "steelman_of_attack": "C1",
                "what_would_vindicate_the_debater": "D1",
            },
            "quant": {
                "load_bearing_assumption": "A2",
                "attack": "B2",
                "steelman_of_attack": "C2",
                "what_would_vindicate_the_debater": "D2",
            },
            "empiricist": {
                "load_bearing_assumption": "A3",
                "attack": "B3",
                "steelman_of_attack": "C3",
                "what_would_vindicate_the_debater": "D3",
            },
            "ethicist": {
                "load_bearing_assumption": "A4",
                "attack": "B4",
                "steelman_of_attack": "C4",
                "what_would_vindicate_the_debater": "D4",
            },
        },
        "convergence_flag": {
            "kind": "none",
            "debaters_involved": [],
            "explanation": "",
        },
    }

    from pydantic_ai.messages import ToolCallPart

    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # Call the final_result tool (PydanticAI's structured output mechanism)
        # with our payload as JSON-serialised args.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args=json.dumps(payload),
                    tool_call_id="tc_critic_1",
                ),
            ],
        )

    return FunctionModel(_fn)


class TestCriticAgent:
    @pytest.mark.asyncio
    async def test_run_produces_valid_critic_report(self, critic_deps):
        agent = create_agent(_make_critic_function_model())
        result = await agent.run(
            "Critique the positions in this round.",
            deps=critic_deps,
        )
        assert isinstance(result.output, CriticReport)
        # The schema-enforced four-key contract.
        assert set(result.output.attacks.keys()) == {
            "systems",
            "quant",
            "empiricist",
            "ethicist",
        }
        # Convergence flag is required.
        assert result.output.convergence_flag is not None

    def test_yaml_matches_agent_config_schema(self):
        from modules.backend.schemas.agent_config import AgentConfigSchema

        path = find_project_root() / "config" / "agents" / "deliberation" / "critic" / "agent.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = AgentConfigSchema(**raw)
        assert config.agent_name == "deliberation.critic.agent"
        assert config.model.name == "copilot:claude-opus-4.6"
        # Critic temperature is 0.4 per §6.1 — sharper than debaters (0.7)
        # but not 0.0 (some variance in attack strength).
        assert config.model.temperature == 0.4
        # Critic has no tools — it reasons on its input.
        assert config.tools == []

    def test_prompt_loads_with_critic_content(self):
        from modules.backend.agents.mission_control.helpers import assemble_instructions

        prompt = assemble_instructions("deliberation", "critic")
        assert "Critic" in prompt
        # Core critic vocabulary.
        assert "load-bearing assumption" in prompt.lower()
        assert "attack" in prompt.lower()
        assert "steelman" in prompt.lower()
        # The four convergence-flag kinds — these are the
        # sycophancy-detection vocabulary.
        for kind in (
            "shared_hidden_assumption",
            "paraphrase",
            "collapse_to_mainstream",
        ):
            assert kind in prompt
        # The early-stop note (Plan 79 §6) — must tell the critic NOT to
        # rely on the stance-delta as a quality measure.
        assert "early-stop" in prompt.lower() or "stopping signal" in prompt.lower()

    def test_prompt_enforces_independence_across_rounds(self):
        """The critic must NOT see its own prior reports. The prompt
        must explicitly state this so the model does not retain a
        committed line across rounds."""
        from modules.backend.agents.mission_control.helpers import assemble_instructions

        prompt = assemble_instructions("deliberation", "critic")
        assert "independent" in prompt.lower()
