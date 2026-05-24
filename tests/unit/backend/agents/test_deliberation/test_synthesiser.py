"""Deliberation Synthesiser Agent tests (Plan 79 Phase 6).

The synthesiser's output schema FinalDeliverable has the strictest
validators in Plan 79 (cruxes min_length=2, required minority_position,
deliberation_vs_mainstream enum including merely_reproduces,
report_markdown min_length=200, etc). TestModel does not auto-satisfy
these — we use FunctionModel to return a known-valid payload.
"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from modules.backend.agents.deliberation.synthesiser.agent import create_agent
from modules.backend.agents.deps.base import BaseAgentDeps, FileScope
from modules.backend.core.config import find_project_root
from modules.backend.schemas.deliberation import FinalDeliverable


@pytest.fixture
def synthesiser_deps():
    return BaseAgentDeps(
        project_root=find_project_root(),
        scope=FileScope(read_paths=[], write_paths=[]),
    )


def _valid_payload(**overrides) -> dict:
    """A schema-valid FinalDeliverable dict. Overrides let tests probe
    specific anti-flattening guarantees."""
    base = {
        "question_restated": "Will X happen by 2030?",
        "committed_answer": "Yes, in the moderate scenario, with caveats.",
        "confidence": 0.65,
        "cruxes": [
            {
                "crux_question": "Does Y depend on Z?",
                "side_a_position": "Yes",
                "side_a_debaters": ["systems"],
                "side_a_steelman": "Strong reason for yes.",
                "side_b_position": "No",
                "side_b_debaters": ["quant"],
                "side_b_steelman": "Strong reason for no.",
                "resolving_evidence": "If we observed W.",
            },
            {
                "crux_question": "Is A in scope?",
                "side_a_position": "In scope",
                "side_a_debaters": ["empiricist"],
                "side_a_steelman": "Track record says yes.",
                "side_b_position": "Out of scope",
                "side_b_debaters": ["ethicist"],
                "side_b_steelman": "Distribution argues otherwise.",
                "resolving_evidence": "Real-world signal B.",
            },
        ],
        "minority_position": None,
        "mainstream_prior": "Conventional answer X.",
        "deliberation_vs_mainstream": "modifies",
        "forward_claim": {
            "horizon": "by 2030",
            "most_likely": "Y will dominate.",
            "plausible_alternative": "Y could lose to Z.",
            "would_surprise_the_system": "W happens.",
            "falsifiers": ["If observation V occurs before 2028."],
        },
        "biggest_things_that_could_be_wrong": [
            "Assumption about A is wrong.",
            "Mechanism about B does not hold.",
        ],
        "sycophancy_flags": [],
        "report_markdown": (
            "# Deliverable\n\n## Question\n\nWill X happen by 2030?\n\n"
            "## Answer\n\nYes with caveats.\n\n## Cruxes\n\n"
            "1. Does Y depend on Z?\n2. Is A in scope?\n\n"
            "## Mainstream Prior\n\nConventional answer X.\n\n"
            "## Forward Claim\n\nBy 2030, Y will dominate."
        ),
        "recommendation_markdown": (
            "Watch for: changes in A and breakdown of mechanism B."
        ),
    }
    base.update(overrides)
    return base


def _make_synthesiser_function_model(payload: dict) -> FunctionModel:
    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args=json.dumps(payload),
                    tool_call_id="tc_synth_1",
                ),
            ],
        )

    return FunctionModel(_fn)


class TestSynthesiserAgent:
    @pytest.mark.asyncio
    async def test_run_produces_valid_final_deliverable(self, synthesiser_deps):
        agent = create_agent(_make_synthesiser_function_model(_valid_payload()))
        result = await agent.run("Synthesise.", deps=synthesiser_deps)
        assert isinstance(result.output, FinalDeliverable)
        assert len(result.output.cruxes) == 2
        assert result.output.deliberation_vs_mainstream == "modifies"

    @pytest.mark.asyncio
    async def test_run_with_merely_reproduces_flag(self, synthesiser_deps):
        # The whole point of Plan 79: this enum value MUST round-trip
        # through the agent. If the synthesiser ever flags
        # merely_reproduces, the structured artifact carries it.
        payload = _valid_payload(deliberation_vs_mainstream="merely_reproduces")
        agent = create_agent(_make_synthesiser_function_model(payload))
        result = await agent.run("Synthesise.", deps=synthesiser_deps)
        assert result.output.deliberation_vs_mainstream == "merely_reproduces"

    @pytest.mark.asyncio
    async def test_minority_position_preserved(self, synthesiser_deps):
        # The schema requires explicit None vs record. A None synthesis
        # round-trips cleanly; a record synthesis preserves the debater.
        payload = _valid_payload(minority_position={
            "debater": "empiricist",
            "position": "held contrarian view",
            "why_it_survived": "critic could not break it",
            "why_it_merits_preservation": "track record warrants it",
        })
        agent = create_agent(_make_synthesiser_function_model(payload))
        result = await agent.run("Synthesise.", deps=synthesiser_deps)
        assert result.output.minority_position is not None
        assert result.output.minority_position.debater == "empiricist"

    def test_yaml_matches_agent_config_schema(self):
        from modules.backend.schemas.agent_config import AgentConfigSchema

        path = (
            find_project_root()
            / "config" / "agents" / "deliberation" / "synthesiser" / "agent.yaml"
        )
        with open(path) as f:
            raw = yaml.safe_load(f)
        config = AgentConfigSchema(**raw)
        assert config.agent_name == "deliberation.synthesiser.agent"
        assert config.model.name == "copilot:claude-opus-4.6"
        # The synthesiser receives the full transcript — needs the
        # 1M max_input_length per §6.1.
        assert config.max_input_length == 1_000_000
        # And the raised cost ceiling for the verbose-debater worst case.
        assert config.max_budget_usd == 8.00

    def test_prompt_includes_all_eleven_sections(self):
        """The synthesiser prompt enumerates the 11 required fields of
        the deliverable. If any go missing, the schema validators will
        fail at runtime but the test catches drift earlier."""
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "synthesiser")
        lower = prompt.lower()
        # All FinalDeliverable field names must appear in the prompt.
        for field in (
            "question_restated", "committed_answer", "confidence",
            "cruxes", "minority_position", "mainstream_prior",
            "deliberation_vs_mainstream", "forward_claim",
            "biggest_things_that_could_be_wrong", "sycophancy_flags",
            "report_markdown", "recommendation_markdown",
        ):
            assert field in lower, f"prompt missing field: {field}"

    def test_prompt_includes_merely_reproduces_failure_mode(self):
        """Plan 79 §5 — the synthesiser MUST flag
        deliberation_vs_mainstream='merely_reproduces' when applicable.
        Drift here weakens the anti-flattening machinery."""
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "synthesiser")
        assert "merely_reproduces" in prompt
        assert "failure mode" in prompt.lower()

    def test_prompt_handles_skipped_rounds(self):
        """Plan 79 §6 / S3 fix — the synthesiser prompt explicitly
        tells the model how to handle null entries for skipped rounds."""
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "synthesiser")
        assert "skipped" in prompt.lower()
        assert "null" in prompt.lower() or "None" in prompt

    def test_prompt_has_early_stop_clarification(self):
        from modules.backend.agents.mission_control.helpers import (
            assemble_instructions,
        )

        prompt = assemble_instructions("deliberation", "synthesiser")
        assert "early-stop" in prompt.lower() or "stopping signal" in prompt.lower()
