"""
Tests for WorkflowRunWaves engine helpers introduced by Plan 79:

- §8.2 — _build_step_objective JSON-encodes dict/list values
- §8.3 — _extract_default_agent_output by agent_name (the load-bearing one)
- §8.4 — tool_args deep-resolve (covered via tool_call dispatcher integration
         test, which lives in test_workflow_run_waves_integration.py)
"""

from __future__ import annotations

from modules.backend.schemas.workflow import WorkflowStepSchema
from modules.backend.services.workflow_run_waves import (
    WorkflowRunWavesMixin,
    _extract_default_agent_output,
)


def _make_service():
    # _build_step_objective only needs the bound method, not full service state.
    # We construct a minimal instance via __new__ to avoid dependency-injection
    # overhead.
    return WorkflowRunWavesMixin.__new__(WorkflowRunWavesMixin)


def _make_step(**overrides) -> WorkflowStepSchema:
    base = {
        "id": "step-a",
        "capability": "test.agent",
        "description": "Test step",
    }
    base.update(overrides)
    return WorkflowStepSchema(**base)


# =============================================================================
# §8.2 — _build_step_objective handles dict/list/scalar/None
# =============================================================================


class TestBuildStepObjectiveStructured:
    """Plan 79 §8.2 — dict/list values JSON-encode; None skips; scalars
    format inline."""

    def test_dict_value_json_encoded(self):
        svc = _make_service()
        step = _make_step(description="Process")
        obj = svc._build_step_objective(step, {"data": {"a": 1, "b": 2}})
        assert "Process" in obj
        assert '"a": 1' in obj
        assert '"b": 2' in obj

    def test_list_value_json_encoded(self):
        svc = _make_service()
        step = _make_step(description="Run")
        obj = svc._build_step_objective(step, {"items": [1, 2, 3]})
        assert "items: [1, 2, 3]" in obj

    def test_nested_dict_json_encoded(self):
        # Deliberation sparse-topology pattern: opponents_previous nested dict.
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(
            step,
            {
                "opponents_previous": {
                    "quant": {"position": "Q1"},
                    "ethicist": {"position": "E1"},
                },
            },
        )
        # Both nested values must be present as parseable JSON.
        assert "Q1" in obj
        assert "E1" in obj
        assert "quant" in obj
        assert "ethicist" in obj

    def test_none_value_skipped(self):
        # Skipped predecessors resolve to None; should NOT appear as "key: None".
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(
            step,
            {
                "round_2_position": None,
                "round_1_position": "held",
            },
        )
        assert "None" not in obj
        assert "round_1_position: held" in obj
        # The None key should be omitted entirely.
        assert "round_2_position" not in obj

    def test_scalar_int_formatted(self):
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(step, {"round_index": 2})
        assert "round_index: 2" in obj

    def test_scalar_float_formatted(self):
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(step, {"agreement_intensity": 0.2})
        assert "agreement_intensity: 0.2" in obj

    def test_scalar_bool_formatted(self):
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(step, {"verified": True})
        assert "verified: True" in obj

    def test_string_value_inline(self):
        svc = _make_service()
        step = _make_step()
        obj = svc._build_step_objective(step, {"q": "What is X?"})
        assert "q: What is X?" in obj

    def test_empty_input_no_context_section(self):
        svc = _make_service()
        step = _make_step(description="Just describe")
        obj = svc._build_step_objective(step, {})
        assert obj == "Just describe"

    def test_description_default_when_missing(self):
        svc = _make_service()
        step = _make_step(description=None)
        obj = svc._build_step_objective(step, {})
        # Default falls back to "Execute step: <id>"
        assert "Execute step: step-a" in obj

    def test_mixed_types_in_input(self):
        # Realistic deliberation debater input: question (str) + round_index
        # (int) + agreement_intensity (float) + research_packet (dict) +
        # opponents_previous (dict) + skipped_field (None).
        svc = _make_service()
        step = _make_step(description="Debate")
        obj = svc._build_step_objective(
            step,
            {
                "question": "Will X happen?",
                "round_index": 1,
                "agreement_intensity": 0.2,
                "research_packet": {"consensus": "yes"},
                "opponents_previous": {"quant": {"position": "no"}},
                "skipped_field": None,
            },
        )
        assert "question: Will X happen?" in obj
        assert "round_index: 1" in obj
        assert "agreement_intensity: 0.2" in obj
        assert "consensus" in obj
        assert "quant" in obj
        # None values dropped, not surfaced as "skipped_field: None"
        assert "skipped_field" not in obj


# =============================================================================
# §8.3 — _extract_default_agent_output (LOAD-BEARING)
# =============================================================================


class TestExtractDefaultAgentOutput:
    """Plan 79 §8.3 — without this, every chained @node.X.output ref in
    the deliberation workflow silently resolves to None because
    extract_outputs() returns {} when output_mapping is missing.

    Strategy: match by agent_name (deterministic); fall back to last
    task_result + log warning (legacy multi-task safety net)."""

    def test_empty_outcome_returns_empty(self):
        assert _extract_default_agent_output({}) == {}
        assert _extract_default_agent_output(None) == {}

    def test_no_task_results_returns_empty(self):
        assert _extract_default_agent_output({"task_results": []}) == {}
        assert _extract_default_agent_output({"task_results": None}) == {}

    def test_single_task_result_with_agent_name_match(self):
        outcome = {
            "task_results": [
                {
                    "agent_name": "deliberation.debater_systems.agent",
                    "output_reference": {"position": "X", "confidence": 0.8},
                },
            ],
        }
        result = _extract_default_agent_output(
            outcome,
            expected_agent="deliberation.debater_systems.agent",
        )
        assert result == {"output": {"position": "X", "confidence": 0.8}}

    def test_multiple_task_results_picks_matching_agent(self):
        # Multi-task plan: the agent we care about isn't necessarily last.
        outcome = {
            "task_results": [
                {
                    "agent_name": "deliberation.debater_systems.agent",
                    "output_reference": {"position": "real-debater"},
                },
                {
                    "agent_name": "system.verification.agent",
                    "output_reference": {"verified": True},
                },
                {
                    "agent_name": "system.synthesis.agent",
                    "output_reference": {"summary": "narrative"},
                },
            ],
        }
        # Without agent_name match, [-1] would return the synthesis output.
        # With it, we get the debater's actual output.
        result = _extract_default_agent_output(
            outcome,
            expected_agent="deliberation.debater_systems.agent",
        )
        assert result == {"output": {"position": "real-debater"}}

    def test_falls_back_to_last_when_no_agent_match(self, caplog):
        import logging

        outcome = {
            "task_results": [
                {"agent_name": "agent.one", "output_reference": {"a": 1}},
                {"agent_name": "agent.two", "output_reference": {"b": 2}},
            ],
        }
        with caplog.at_level(logging.WARNING):
            result = _extract_default_agent_output(
                outcome,
                expected_agent="agent.nonexistent",
            )
        assert result == {"output": {"b": 2}}
        # The warning is fired through structlog; the log record carries the
        # expected_agent and available_agent_names. We just assert the result.

    def test_no_expected_agent_falls_back_to_last(self):
        outcome = {
            "task_results": [
                {"agent_name": "one", "output_reference": {"a": 1}},
                {"agent_name": "two", "output_reference": {"b": 2}},
            ],
        }
        result = _extract_default_agent_output(outcome)
        assert result == {"output": {"b": 2}}

    def test_missing_output_reference_returns_empty_output(self):
        outcome = {
            "task_results": [
                {"agent_name": "agent.x"},  # no output_reference
            ],
        }
        result = _extract_default_agent_output(outcome, expected_agent="agent.x")
        assert result == {"output": {}}

    def test_non_dict_task_result_falls_through(self):
        # Defensive: malformed task_results entries shouldn't crash.
        outcome = {"task_results": ["string-not-dict"]}
        result = _extract_default_agent_output(outcome, expected_agent="agent.x")
        # Falls back to last (which is also non-dict), returns empty output.
        assert result == {"output": {}}


# =============================================================================
# §8.4 — tool_call tool_args deep-resolve
# =============================================================================


class TestToolArgsDeepResolve:
    """Plan 79 §8.4 — the tool_call dispatcher uses walk_refs + resolve_template
    to resolve refs inside nested dict/list tool_args. Verified here against a
    representative `compute_stance_delta`-shaped payload."""

    def _resolve(self, tool_args, outcomes, ctx):
        """Mirror the dispatcher's exact resolution call."""
        from modules.backend.services.condition_evaluator import resolve_template, walk_refs

        return walk_refs(
            tool_args,
            outcomes,
            ctx,
            leaf_resolver=lambda s: resolve_template(s, outcomes, ctx),
        )

    def test_resolves_nested_dict_refs(self):
        # compute_stance_delta's previous_round shape.
        outcomes = {
            "round1-systems": {"output": {"position": "S1", "confidence": 0.8}},
            "round1-quant": {"output": {"position": "Q1", "confidence": 0.7}},
        }
        tool_args = {
            "previous_round": {
                "systems": "{{@node.round1-systems.output}}",
                "quant": "{{@node.round1-quant.output}}",
            },
            "threshold": 0.15,
        }
        result = self._resolve(tool_args, outcomes, {})
        assert result["previous_round"]["systems"] == {
            "position": "S1",
            "confidence": 0.8,
        }
        assert result["previous_round"]["quant"] == {
            "position": "Q1",
            "confidence": 0.7,
        }
        # Non-ref scalar passes through.
        assert result["threshold"] == 0.15

    def test_standalone_ref_preserves_type(self):
        # §8.6 type preservation in tool args.
        outcomes = {"x": {"output": {"confidence": 0.85}}}
        tool_args = {"confidence": "{{@node.x.output.confidence}}"}
        result = self._resolve(tool_args, outcomes, {})
        assert result["confidence"] == 0.85
        assert isinstance(result["confidence"], float)

    def test_mixed_text_template_str_coerces(self):
        # When the template is mixed text, the result is a string.
        outcomes = {"x": {"output": "world"}}
        tool_args = {"greeting": "hello {{@node.x.output}}"}
        result = self._resolve(tool_args, outcomes, {})
        assert result["greeting"] == "hello world"

    def test_skipped_predecessor_resolves_to_none(self):
        # Skipped round → None in standalone refs.
        outcomes = {"skipped": {"_skipped": True}}
        tool_args = {"value": "{{@node.skipped.output}}"}
        result = self._resolve(tool_args, outcomes, {})
        assert result["value"] is None

    def test_static_args_pass_through(self):
        tool_args = {"title": "static title", "limit": 5, "tags": ["a", "b"]}
        result = self._resolve(tool_args, {}, {})
        assert result == {"title": "static title", "limit": 5, "tags": ["a", "b"]}

    def test_typo_in_ref_raises(self):
        import pytest

        from modules.backend.services.condition_evaluator import ConditionEvaluationError

        with pytest.raises(ConditionEvaluationError):
            self._resolve(
                {"value": "{{@nodez.x.output}}"},
                {},
                {},
            )

    def test_deliberation_transcript_shape(self):
        # Smoke check on the actual shape used by Plan 79's store-transcript
        # step — a nested dict with @node refs at multiple levels.
        outcomes = {
            "research": {"output": {"consensus": "yes"}},
            "open-systems": {"output": {"position": "S0"}},
            "round1-systems": {"output": {"position": "S1"}},
        }
        tool_args = {
            "title": "Transcript: X",
            "artifact_type": "deliberation_transcript",
            "content": {
                "research_packet": "{{@node.research.output}}",
                "rounds": {
                    "round_0": {"systems": "{{@node.open-systems.output}}"},
                    "round_1": {"systems": "{{@node.round1-systems.output}}"},
                },
            },
        }
        result = self._resolve(tool_args, outcomes, {})
        assert result["title"] == "Transcript: X"
        assert result["content"]["research_packet"] == {"consensus": "yes"}
        assert result["content"]["rounds"]["round_0"]["systems"] == {"position": "S0"}
        assert result["content"]["rounds"]["round_1"]["systems"] == {"position": "S1"}
