"""
Tests for step-level inline condition evaluation in the wave executor.

Validates that WorkflowRunWavesMixin._should_skip correctly handles:
- Steps with no inline condition (backward-compatible)
- Steps with a true inline condition (not skipped)
- Steps with a false inline condition (skipped)
- Inline conditions combined with graph-based condition routing
- Skip propagation from a conditionally-skipped parent
"""

import pytest

from modules.backend.schemas.workflow import WorkflowStepSchema
from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin


def _step(
    step_id: str,
    depends_on: list[str] | None = None,
    node_type: str = "agent_step",
    condition: str | None = None,
    condition_config: dict | None = None,
) -> WorkflowStepSchema:
    kwargs: dict = {
        "id": step_id,
        "node_type": node_type,
        "depends_on": depends_on or [],
    }
    if node_type == "agent_step":
        kwargs["capability"] = "test.agent"
    if condition is not None:
        kwargs["condition"] = condition
    if condition_config is not None:
        kwargs["condition_config"] = condition_config
    return WorkflowStepSchema(**kwargs)


class TestInlineConditionSkip:
    """Inline condition on agent_step nodes."""

    def test_no_condition_runs(self):
        step = _step("a")
        step_map = {"a": step}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}) is False

    def test_true_condition_runs(self):
        step = _step("a", condition='@context.target_path != null')
        step_map = {"a": step}
        ctx = {"target_path": "/some/path"}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, ctx) is False

    def test_false_condition_skips(self):
        step = _step("a", condition='@context.target_path != null')
        step_map = {"a": step}
        ctx = {"target_path": None}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, ctx) is True

    def test_missing_context_key_skips(self):
        """If the referenced key is absent from context, it resolves to None."""
        step = _step("a", condition='@context.nonexistent != null')
        step_map = {"a": step}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, {}) is True

    def test_condition_with_string_equality(self):
        step = _step("a", condition='@context.mode == "full"')
        step_map = {"a": step}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, {"mode": "full"}) is False
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, {"mode": "lite"}) is True

    def test_condition_with_node_reference(self):
        """Condition referencing a completed upstream step's output."""
        step = _step("b", depends_on=["a"], condition='@node.a.score >= 0.7')
        step_map = {"a": _step("a"), "b": step}
        outcomes = {"a": {"score": 0.8}}
        assert WorkflowRunWavesMixin._should_skip("b", step_map, outcomes, {}) is False

        outcomes_low = {"a": {"score": 0.3}}
        assert WorkflowRunWavesMixin._should_skip("b", step_map, outcomes_low, {}) is True

    def test_malformed_condition_skips(self):
        """A condition that fails to parse should skip (fail safe)."""
        step = _step("a", condition="@@@@invalid")
        step_map = {"a": step}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, {}, {}, {}) is True


class TestGraphConditionUnchanged:
    """Existing graph-based condition routing still works."""

    def test_condition_branch_match_runs(self):
        cond = _step("cond", node_type="condition", condition_config={
            "expression": "@context.mode == \"full\"",
            "true_label": "Yes",
            "false_label": "No",
        })
        step = _step("a", depends_on=["cond"])
        step_map = {"cond": cond, "a": step}
        outcomes = {"cond": {"_branch": "Yes"}}
        edges = {("cond", "a"): "Yes"}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, outcomes, edges) is False

    def test_condition_branch_mismatch_skips(self):
        cond = _step("cond", node_type="condition", condition_config={
            "expression": "@context.mode == \"full\"",
            "true_label": "Yes",
            "false_label": "No",
        })
        step = _step("a", depends_on=["cond"])
        step_map = {"cond": cond, "a": step}
        outcomes = {"cond": {"_branch": "No"}}
        edges = {("cond", "a"): "Yes"}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, outcomes, edges) is True

    def test_skip_propagation(self):
        parent = _step("parent")
        child = _step("child", depends_on=["parent"])
        step_map = {"parent": parent, "child": child}
        outcomes = {"parent": {"_skipped": True}}
        assert WorkflowRunWavesMixin._should_skip("child", step_map, outcomes, {}) is True


class TestInlineAndGraphCombined:
    """Steps with both an inline condition AND a graph condition dependency."""

    def test_inline_false_skips_even_if_graph_passes(self):
        """Inline condition is checked first — if false, step is skipped."""
        cond = _step("cond", node_type="condition", condition_config={
            "expression": "true",
            "true_label": "Yes",
            "false_label": "No",
        })
        step = _step("a", depends_on=["cond"], condition='@context.enabled != null')
        step_map = {"cond": cond, "a": step}
        outcomes = {"cond": {"_branch": "Yes"}}
        edges = {("cond", "a"): "Yes"}
        ctx = {"enabled": None}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, outcomes, edges, ctx) is True

    def test_inline_true_but_graph_mismatch_skips(self):
        """Inline condition passes but graph branch doesn't match — still skipped."""
        cond = _step("cond", node_type="condition", condition_config={
            "expression": "true",
            "true_label": "Yes",
            "false_label": "No",
        })
        step = _step("a", depends_on=["cond"], condition='@context.enabled != null')
        step_map = {"cond": cond, "a": step}
        outcomes = {"cond": {"_branch": "No"}}
        edges = {("cond", "a"): "Yes"}
        ctx = {"enabled": "yes"}
        assert WorkflowRunWavesMixin._should_skip("a", step_map, outcomes, edges, ctx) is True
