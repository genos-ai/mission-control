"""
Tests for workflow YAML validation schemas.

Pure Pydantic schema tests — no mocks, no infrastructure.
"""

import pytest

from modules.backend.schemas.workflow import (
    WorkflowBudgetSchema,
    WorkflowEdgeSchema,
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


class TestStepConditionField:
    """Tests for the inline ``condition`` field on WorkflowStepSchema."""

    def test_condition_none_by_default(self):
        step = WorkflowStepSchema(id="step-one", capability="test.agent")
        assert step.condition is None

    def test_condition_accepted(self):
        step = WorkflowStepSchema(
            id="step-one",
            capability="test.agent",
            condition='@context.target_path != null',
        )
        assert step.condition == '@context.target_path != null'

    def test_condition_max_length(self):
        with pytest.raises(ValueError):
            WorkflowStepSchema(
                id="step-one",
                capability="test.agent",
                condition="x" * 501,
            )

    def test_condition_empty_string_accepted(self):
        """Empty string is accepted by schema (evaluator handles it)."""
        step = WorkflowStepSchema(
            id="step-one",
            capability="test.agent",
            condition="",
        )
        assert step.condition == ""

    def test_condition_in_full_workflow(self):
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "step-a", "capability": "test.agent"},
                {
                    "id": "step-b",
                    "capability": "test.agent",
                    "depends_on": ["step-a"],
                    "condition": '@context.mode == "full"',
                },
            ],
        ))
        assert workflow.steps[1].condition == '@context.mode == "full"'

    def test_condition_does_not_break_existing_steps(self):
        """Existing steps without condition continue to work."""
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "step-a", "capability": "test.agent",
                 "output_mapping": {"summary_key": "a_result"}},
                {"id": "step-b", "capability": "test.agent",
                 "depends_on": ["step-a"]},
            ],
        ))
        assert workflow.steps[0].condition is None
        assert workflow.steps[1].condition is None


# =============================================================================
# §8.7 — load-time validation of @node.X refs
# =============================================================================


class TestNodeRefLoadTimeValidation:
    """Plan 79 §8.7 — validate_steps scans step.input, tool_args, prompts,
    decision configs, etc. for @node.<step_id> references and raises
    ValueError at workflow parse time if any name a non-existent step.

    Catches typos like @node.opem-systems.output (missing 'n') before the
    workflow runs for hours and silently passes through the wrong values."""

    def test_valid_node_ref_accepted(self):
        WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "step-a", "capability": "test.agent"},
                {
                    "id": "step-b", "capability": "test.agent",
                    "depends_on": ["step-a"],
                    "input": {"data": "@node.step-a.output"},
                },
            ],
        ))

    def test_typo_in_step_input_raises(self):
        # Classic typo: opem-systems instead of open-systems.
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {
                        "id": "step-b", "capability": "test.agent",
                        "depends_on": ["step-a"],
                        "input": {"data": "@node.steo-a.output"},
                    },
                ],
            ))

    def test_typo_in_nested_dict_input_raises(self):
        # Deliberation sparse-topology pattern: ref nested inside a dict.
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "open-systems", "capability": "test.agent"},
                    {"id": "open-quant", "capability": "test.agent"},
                    {
                        "id": "round1-systems", "capability": "test.agent",
                        "depends_on": ["open-systems", "open-quant"],
                        "input": {
                            "opponents_previous": {
                                "quant": "@node.open-qaunt.output",  # typo
                            },
                        },
                    },
                ],
            ))

    def test_typo_in_tool_args_raises(self):
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {
                        "id": "step-store", "node_type": "tool_call",
                        "depends_on": ["step-a"],
                        "tool_call_config": {
                            "tool_name": "store_artifact",
                            "tool_args": {
                                "title": "X",
                                "content": "{{@node.step-aa.output}}",
                            },
                        },
                    },
                ],
            ))

    def test_typo_in_llm_call_prompt_template_raises(self):
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {
                        "id": "step-render", "node_type": "llm_call",
                        "depends_on": ["step-a"],
                        "llm_call_config": {
                            "model": "copilot:claude-haiku-4.5",
                            "prompt_template": "Render {{@node.misspelt.output}}",
                        },
                    },
                ],
            ))

    def test_typo_in_decision_expression_raises(self):
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {
                        "id": "step-decide", "node_type": "decision",
                        "depends_on": ["step-a"],
                        "decision_config": {
                            "resolver": "rule",
                            "expression": "@node.step-misspelt.output.passed == true",
                            "options": [
                                {"key": "yes", "label": "Yes"},
                                {"key": "no", "label": "No"},
                            ],
                        },
                    },
                ],
            ))

    def test_typo_in_condition_field_raises(self):
        with pytest.raises(ValueError, match="references unknown step IDs"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {
                        "id": "step-b", "capability": "test.agent",
                        "depends_on": ["step-a"],
                        "condition": "@node.step-aa.output is_not_empty",
                    },
                ],
            ))

    def test_context_refs_unaffected(self):
        # @context.X refs are not validated by §8.7 (no schema for workflow
        # parameters in WorkflowStepSchema). Only @node refs are checked.
        WorkflowSchema(**_minimal_workflow(
            steps=[
                {
                    "id": "step-a", "capability": "test.agent",
                    "input": {"q": "@context.question"},  # unknown context key is fine here
                },
            ],
        ))

    def test_error_lists_available_step_ids(self):
        with pytest.raises(ValueError, match="Available:"):
            WorkflowSchema(**_minimal_workflow(
                steps=[
                    {"id": "step-a", "capability": "test.agent"},
                    {"id": "step-b", "capability": "test.agent"},
                    {
                        "id": "step-c", "capability": "test.agent",
                        "depends_on": ["step-a"],
                        "input": {"data": "@node.step-z.output"},
                    },
                ],
            ))

    def test_existing_workflows_still_parse(self):
        """Sanity: every existing workflow template still loads under §8.7."""
        import glob

        import yaml

        for path in sorted(glob.glob("config/workflow_templates/*.yaml")):
            with open(path) as f:
                data = yaml.safe_load(f)
            WorkflowSchema(**data)


# =============================================================================
# WorkflowEdgeSchema — id auto-fill (visual-editor edge persistence)
# =============================================================================


class TestWorkflowEdgeSchemaIdAutoFill:
    """When YAML omits the edge `id` it must be synthesised deterministically
    so React Flow does not collapse multiple edges sharing the same default
    key — notably the four `passed`/`continue` edges leaving decision nodes."""

    def test_id_synthesised_with_default_handle(self):
        edge = WorkflowEdgeSchema(source="step-a", target="step-b")
        assert edge.id == "step-a->step-b"

    def test_id_synthesised_with_named_source_handle(self):
        edge = WorkflowEdgeSchema(
            source="research-gate",
            target="open-systems",
            source_handle="passed",
        )
        assert edge.id == "research-gate:passed->open-systems"

    def test_explicit_id_preserved(self):
        edge = WorkflowEdgeSchema(
            id="custom-id",
            source="step-a",
            target="step-b",
            source_handle="passed",
        )
        assert edge.id == "custom-id"

    def test_default_output_handle_collapses_to_simple_form(self):
        edge = WorkflowEdgeSchema(
            source="step-a",
            target="step-b",
            source_handle="output",
        )
        assert edge.id == "step-a->step-b"

    def test_workflow_loaded_with_idless_edges_validates(self):
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "step-a", "capability": "test.agent"},
                {"id": "step-b", "capability": "test.agent",
                 "depends_on": ["step-a"]},
            ],
            edges=[
                {"source": "step-a", "target": "step-b"},
            ],
        ))
        assert len(workflow.edges) == 1
        assert workflow.edges[0].id == "step-a->step-b"

    def test_decision_node_fan_out_edges_get_unique_ids(self):
        """Decision-node siblings must not collide on edge id — the visual
        editor regression that motivated this contract."""
        workflow = WorkflowSchema(**_minimal_workflow(
            steps=[
                {"id": "gate", "node_type": "decision",
                 "decision_config": {
                     "resolver": "rule",
                     "expression": "@node.gate.output.passed == true",
                     "options": [
                         {"key": "passed", "label": "Passed"},
                         {"key": "failed", "label": "Failed"},
                     ],
                 }},
                {"id": "a", "capability": "test.agent", "depends_on": ["gate"]},
                {"id": "b", "capability": "test.agent", "depends_on": ["gate"]},
                {"id": "c", "capability": "test.agent", "depends_on": ["gate"]},
            ],
            edges=[
                {"source": "gate", "target": "a", "source_handle": "passed"},
                {"source": "gate", "target": "b", "source_handle": "passed"},
                {"source": "gate", "target": "c", "source_handle": "passed"},
            ],
        ))
        ids = [e.id for e in workflow.edges]
        assert ids == [
            "gate:passed->a",
            "gate:passed->b",
            "gate:passed->c",
        ]
        assert len(set(ids)) == 3
