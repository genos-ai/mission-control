"""
Tests for workflow YAML validation schemas.

Pure Pydantic schema tests — no mocks, no infrastructure.
"""

import pytest

from modules.backend.schemas.workflow import (
    WorkflowBudgetSchema,
    WorkflowObjectiveSchema,
    WorkflowOutputFieldMapping,
    WorkflowSchema,
    WorkflowStepOutputMapping,
    WorkflowStepSchema,
    WorkflowTriggerSchema,
)


def _minimal_workflow(**overrides):
    """Build a minimal valid workflow dict."""
    base = {
        "workflow_name": "test.example.workflow",
        "description": "Test workflow",
        "objective": {
            "statement": "Test objective",
            "category": "testing",
            "owner": "test-owner",
            "priority": "normal",
        },
        "steps": [
            {"id": "step-one", "capability": "test.agent"},
        ],
    }
    base.update(overrides)
    return base


class TestWorkflowStepSchema:
    def test_minimal_step(self):
        step = WorkflowStepSchema(id="step-one", capability="test.agent")
        assert step.id == "step-one"
        assert step.roster == "default"
        assert step.complexity_tier == "simple"
        assert step.environment == "local"
        assert step.cost_ceiling_usd is None

    def test_full_step(self):
        step = WorkflowStepSchema(
            id="research",
            description="Research step",
            capability="research.scraper",
            roster="research_team",
            complexity_tier="complex",
            cost_ceiling_usd=5.0,
            environment="container",
            input={"key": "value"},
            output_mapping={"summary_key": "result"},
            depends_on=["prior-step"],
            timeout_seconds=300,
        )
        assert step.complexity_tier == "complex"
        assert step.roster == "research_team"
        assert step.cost_ceiling_usd == 5.0

    def test_invalid_complexity_tier(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(
                id="step", capability="test.agent",
                complexity_tier="medium",
            )

    def test_invalid_environment(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(
                id="step", capability="test.agent",
                environment="docker",
            )

    def test_invalid_id_pattern(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(id="Step-One", capability="test.agent")

    def test_invalid_capability_pattern(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(id="step", capability="singleword")

    def test_cost_ceiling_minimum(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(
                id="step", capability="test.agent",
                cost_ceiling_usd=0.001,
            )


class TestWorkflowOutputMapping:
    def test_summary_key_only(self):
        mapping = WorkflowStepOutputMapping(summary_key="result")
        assert mapping.summary_key == "result"
        assert mapping.field_mappings == []

    def test_field_mappings(self):
        mapping = WorkflowStepOutputMapping(
            field_mappings=[
                WorkflowOutputFieldMapping(
                    source_task="task_1",
                    source_field="output",
                    target_key="data",
                ),
            ],
        )
        assert len(mapping.field_mappings) == 1
        assert mapping.field_mappings[0].target_key == "data"

    def test_invalid_target_key_pattern(self):
        with pytest.raises(ValueError):
            WorkflowOutputFieldMapping(
                source_task="t", source_field="f",
                target_key="Invalid-Key",
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValueError):
            WorkflowStepOutputMapping(unknown="field")


class TestWorkflowTriggerSchema:
    def test_defaults(self):
        trigger = WorkflowTriggerSchema()
        assert trigger.type == "on_demand"
        assert trigger.match_patterns == []

    def test_with_patterns(self):
        trigger = WorkflowTriggerSchema(
            type="on_demand",
            match_patterns=["ai news", "digest"],
        )
        assert len(trigger.match_patterns) == 2

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            WorkflowTriggerSchema(type="webhook")


class TestWorkflowBudgetSchema:
    def test_defaults(self):
        budget = WorkflowBudgetSchema()
        assert budget.max_cost_usd == 10.00
        assert budget.max_tokens is None

    def test_custom(self):
        budget = WorkflowBudgetSchema(max_cost_usd=50.0, max_tokens=100000)
        assert budget.max_cost_usd == 50.0
        assert budget.max_tokens == 100000


class TestWorkflowObjectiveSchema:
    def test_valid(self):
        obj = WorkflowObjectiveSchema(
            statement="Keep team informed",
            category="research",
            owner="eng-lead",
            priority="high",
        )
        assert obj.priority == "high"
        assert obj.regulatory_reference is None

    def test_with_regulatory_ref(self):
        obj = WorkflowObjectiveSchema(
            statement="Compliance check",
            category="compliance",
            owner="ciso",
            priority="critical",
            regulatory_reference="Basel III Pillar 2",
        )
        assert obj.regulatory_reference == "Basel III Pillar 2"

    def test_invalid_priority(self):
        with pytest.raises(ValueError):
            WorkflowObjectiveSchema(
                statement="X", category="x", owner="x",
                priority="urgent",
            )

    def test_invalid_category_pattern(self):
        with pytest.raises(ValueError):
            WorkflowObjectiveSchema(
                statement="X", category="Bad Category", owner="x",
                priority="normal",
            )


class TestWorkflowSchema:
    def test_minimal_valid(self):
        workflow = WorkflowSchema(**_minimal_workflow())
        assert workflow.workflow_name == "test.example.workflow"
        assert len(workflow.steps) == 1
        assert workflow.version == 1
        assert workflow.enabled is True

    def test_extra_fields_rejected(self):
        with pytest.raises(ValueError):
            WorkflowSchema(**_minimal_workflow(unknown_field="oops"))

    def test_duplicate_step_ids(self):
        with pytest.raises(ValueError, match="Duplicate step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {"id": "step-a", "capability": "test.other"},
                ],
            ))

    def test_missing_dependency(self):
        with pytest.raises(ValueError, match="does not exist"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent",
                     "depends_on": ["step-z"]},
                ],
            ))

    def test_self_dependency(self):
        with pytest.raises(ValueError, match="depends on itself"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent",
                     "depends_on": ["step-a"]},
                ],
            ))

    def test_cycle_detection(self):
        with pytest.raises(ValueError, match="dependency cycle"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent",
                     "depends_on": ["step-b"]},
                    {"id": "step-b", "capability": "test.agent",
                     "depends_on": ["step-a"]},
                ],
            ))

    def test_duplicate_output_mapping_keys(self):
        with pytest.raises(ValueError, match="Duplicate output mapping"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent",
                     "output_mapping": {"summary_key": "result"}},
                    {"id": "step-b", "capability": "test.agent",
                     "output_mapping": {"summary_key": "result"}},
                ],
            ))

    def test_valid_dependency_chain(self):
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "step-a", "capability": "test.agent",
                 "output_mapping": {"summary_key": "a_result"}},
                {"id": "step-b", "capability": "test.agent",
                 "depends_on": ["step-a"],
                 "output_mapping": {"summary_key": "b_result"}},
                {"id": "step-c", "capability": "test.agent",
                 "depends_on": ["step-a", "step-b"]},
            ],
        ))
        assert len(workflow.steps) == 3

    def test_roster_and_complexity_per_step(self):
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "research", "capability": "test.agent",
                 "roster": "research_team", "complexity_tier": "complex"},
                {"id": "content", "capability": "test.agent",
                 "roster": "content_team", "complexity_tier": "simple",
                 "depends_on": ["research"]},
            ],
        ))
        assert workflow.steps[0].roster == "research_team"
        assert workflow.steps[0].complexity_tier == "complex"
        assert workflow.steps[1].roster == "content_team"

    def test_invalid_workflow_name(self):
        with pytest.raises(ValueError):
            WorkflowSchema(**_minimal_workflow(workflow_name="BadName"))

    def test_empty_steps_rejected(self):
        with pytest.raises(ValueError):
            WorkflowSchema(**_minimal_workflow(steps=[]))
