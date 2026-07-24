"""Tests for workflow design tool implementations."""

from modules.backend.agents.adapters.workflow_design import (
    build_graph_structure,
    validate_workflow_proposal,
)


class TestValidateWorkflowProposal:
    """Tests for validate_workflow_proposal."""

    def _minimal_step(self, step_id: str = "step-1", **overrides) -> dict:
        base = {
            "id": step_id,
            "capability": "code.review.agent",
            "description": "Test step",
            "depends_on": [],
            "complexity_tier": "simple",
            "environment": "local",
        }
        base.update(overrides)
        return base

    def test_valid_single_step(self):
        result = validate_workflow_proposal([self._minimal_step()])
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["step_count"] == 1

    def test_empty_steps_invalid(self):
        result = validate_workflow_proposal([])
        assert result["valid"] is False
        assert "at least one step" in result["errors"][0]

    def test_valid_chain(self):
        steps = [
            self._minimal_step("plan"),
            self._minimal_step("implement", depends_on=["plan"]),
            self._minimal_step("verify", depends_on=["implement"]),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is True
        assert result["step_count"] == 3

    def test_valid_fan_out(self):
        steps = [
            self._minimal_step("gather"),
            self._minimal_step("review-a", depends_on=["gather"]),
            self._minimal_step("review-b", depends_on=["gather"]),
            self._minimal_step("synthesize", depends_on=["review-a", "review-b"]),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is True

    def test_duplicate_step_ids(self):
        steps = [
            self._minimal_step("dup"),
            self._minimal_step("dup"),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False
        assert any("Duplicate" in e for e in result["errors"])

    def test_missing_dependency(self):
        steps = [
            self._minimal_step("step-1", depends_on=["nonexistent"]),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False
        assert any("nonexistent" in e for e in result["errors"])

    def test_self_dependency(self):
        steps = [
            self._minimal_step("loop", depends_on=["loop"]),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False
        assert any("depends on itself" in e for e in result["errors"])

    def test_cycle_detection(self):
        steps = [
            self._minimal_step("a", depends_on=["b"]),
            self._minimal_step("b", depends_on=["a"]),
        ]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])

    def test_invalid_step_schema(self):
        steps = [{"id": "bad", "capability": "INVALID"}]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_complexity_tier(self):
        steps = [self._minimal_step("s1", complexity_tier="tier_99")]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False

    def test_invalid_environment(self):
        steps = [self._minimal_step("s1", environment="docker")]
        result = validate_workflow_proposal(steps)
        assert result["valid"] is False


class TestBuildGraphStructure:
    """Tests for build_graph_structure."""

    def test_single_node(self):
        steps = [{"id": "step-1", "description": "Do stuff", "capability": "c.d.e"}]
        graph = build_graph_structure(steps)
        assert len(graph["nodes"]) == 1
        assert len(graph["edges"]) == 0
        assert graph["nodes"][0]["id"] == "step-1"

    def test_chain_edges(self):
        steps = [
            {"id": "a", "description": "A", "depends_on": []},
            {"id": "b", "description": "B", "depends_on": ["a"]},
            {"id": "c", "description": "C", "depends_on": ["b"]},
        ]
        graph = build_graph_structure(steps)
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2
        assert {"source": "a", "target": "b"} in graph["edges"]
        assert {"source": "b", "target": "c"} in graph["edges"]

    def test_fan_out_edges(self):
        steps = [
            {"id": "root", "depends_on": []},
            {"id": "left", "depends_on": ["root"]},
            {"id": "right", "depends_on": ["root"]},
        ]
        graph = build_graph_structure(steps)
        assert len(graph["edges"]) == 2

    def test_node_attributes(self):
        steps = [
            {
                "id": "s1",
                "description": "Do things",
                "capability": "code.qa.agent",
                "complexity_tier": "complex",
                "environment": "sandbox",
            }
        ]
        graph = build_graph_structure(steps)
        node = graph["nodes"][0]
        assert node["label"] == "Do things"
        assert node["capability"] == "code.qa.agent"
        assert node["complexity_tier"] == "complex"
        assert node["environment"] == "sandbox"
