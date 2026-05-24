"""Deliberation Think Tank workflow YAML — v2 structural assertions (Plan 79).

v2 collapses the 34-step wave-engine workflow into ONE step with
input.type=deliberation_loop, routed by the dispatch loop to
execute_deliberation_loop(). Tests verify the YAML wiring still matches
the agreed contract.

The v1 workflow lives at
config/workflow_templates/deliberation.think-tank.v1.workflow.yaml
for reference only — not asserted here.
"""

from __future__ import annotations

import pytest
import yaml

from modules.backend.core.config import find_project_root
from modules.backend.schemas.workflow import WorkflowSchema


@pytest.fixture(scope="module")
def workflow() -> WorkflowSchema:
    path = (
        find_project_root() / "config" / "workflow_templates"
        / "deliberation.think-tank.workflow.yaml"
    )
    with open(path) as f:
        raw = yaml.safe_load(f)
    return WorkflowSchema(**raw)


class TestSingleStepShape:
    """v2 should be a single step with type=deliberation_loop."""

    def test_exactly_one_step(self, workflow):
        assert len(workflow.steps) == 1

    def test_step_id(self, workflow):
        assert workflow.steps[0].id == "deliberate"

    def test_node_type_is_agent_step(self, workflow):
        # The dispatch loop's task_type check happens on the
        # already-decomposed task — the WORKFLOW step is still an
        # agent_step (default node type).
        assert workflow.steps[0].node_type == "agent_step"

    def test_capability_is_deliberation_researcher(self, workflow):
        # The capability is nominal — the dispatch routes by
        # input.type=deliberation_loop, not by capability.
        assert workflow.steps[0].capability == "deliberation.researcher"

    def test_input_type_is_deliberation_loop(self, workflow):
        # This is THE key wiring: tells dispatch/loop.py to call
        # _dispatch_deliberation_loop instead of the standard path.
        assert workflow.steps[0].input.get("type") == "deliberation_loop"


class TestParameterPassThrough:
    """Workflow parameters resolve into the executor's loop_config."""

    def test_question_resolves_from_context(self, workflow):
        assert workflow.steps[0].input.get("question") == "@context.question"

    def test_loop_config_has_all_knobs(self, workflow):
        cfg = workflow.steps[0].input.get("loop_config", {})
        assert "max_rounds" in cfg
        assert "agreement_intensity" in cfg
        assert "early_stop_threshold" in cfg
        assert "verifier_max_retries" in cfg

    def test_workflow_declares_question_parameter(self, workflow):
        params = {p.key: p for p in workflow.parameters}
        assert "question" in params
        assert params["question"].required is True

    def test_workflow_declares_tuning_knobs(self, workflow):
        params = {p.key for p in workflow.parameters}
        assert "max_rounds" in params
        assert "agreement_intensity" in params
        assert "early_stop_threshold" in params
        assert "verifier_max_retries" in params


class TestBudgetAndTimeout:
    def test_budget_covers_step_ceiling(self, workflow):
        # Single step, ceiling 150, budget 150 — exact match is fine.
        step_ceiling = workflow.steps[0].cost_ceiling_usd or 0
        assert workflow.budget.max_cost_usd >= step_ceiling

    def test_step_has_generous_timeout(self, workflow):
        # Inner deliberation runs 30-60 min; 90 min ceiling.
        assert (workflow.steps[0].timeout_seconds or 0) >= 1800
