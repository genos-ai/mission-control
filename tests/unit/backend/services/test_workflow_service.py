"""
Tests for WorkflowService.

Tests workflow loading, validation, capability resolution,
mission brief generation, output mapping, and workflow matching.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

import yaml

from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.services.workflow import WorkflowService


def _make_workflow(**overrides) -> WorkflowSchema:
    """Build a valid WorkflowSchema for testing."""
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
    return WorkflowSchema(**base)


class TestCapabilityResolution:
    def test_resolve_with_registry(self):
        registry = {
            "content.summarizer.agent": {
                "agent_name": "content.summarizer.agent",
                "enabled": True,
            },
        }
        service = WorkflowService(agent_registry=registry)
        result = service.resolve_capability("content.summarizer")
        assert result == "content.summarizer.agent"

    def test_resolve_missing_raises(self):
        service = WorkflowService(agent_registry={})
        with pytest.raises(ValueError, match="No agent found"):
            service.resolve_capability("nonexistent.agent")

    def test_resolve_disabled_raises(self):
        registry = {
            "test.disabled.agent": {
                "agent_name": "test.disabled.agent",
                "enabled": False,
            },
        }
        service = WorkflowService(agent_registry=registry)
        with pytest.raises(ValueError, match="disabled"):
            service.resolve_capability("test.disabled")

    def test_validate_workflow_capabilities(self):
        registry = {
            "test.agent.agent": {"agent_name": "test.agent.agent", "enabled": True},
        }
        service = WorkflowService(agent_registry=registry)
        workflow = _make_workflow()
        errors = service.validate_workflow_capabilities(workflow)
        assert errors == []

    def test_validate_capabilities_with_errors(self):
        service = WorkflowService(agent_registry={})
        workflow = _make_workflow()
        errors = service.validate_workflow_capabilities(workflow)
        assert len(errors) == 1
        assert "Step 'step-one'" in errors[0]


class TestMissionBriefGeneration:
    def test_generate_briefs(self):
        registry = {
            "test.step_one.agent": {"agent_name": "test.step_one.agent", "enabled": True},
            "test.step_two.agent": {"agent_name": "test.step_two.agent", "enabled": True},
        }
        service = WorkflowService(agent_registry=registry)

        workflow = WorkflowSchema(
            workflow_name="test.pipeline.workflow",
            description="Test pipeline",
            objective={
                "statement": "Test", "category": "test",
                "owner": "test", "priority": "normal",
            },
            steps=[
                {
                    "id": "step-one",
                    "capability": "test.step_one",
                    "roster": "research_team",
                    "complexity_tier": "complex",
                    "cost_ceiling_usd": 5.0,
                    "input": {"key": "value"},
                    "output_mapping": {"summary_key": "result_one"},
                },
                {
                    "id": "step-two",
                    "capability": "test.step_two",
                    "roster": "content_team",
                    "input": {"data": "@context.result_one"},
                    "depends_on": ["step-one"],
                },
            ],
        )

        briefs = service.generate_mission_briefs(workflow)

        assert len(briefs) == 2
        assert briefs[0]["step_id"] == "step-one"
        assert briefs[0]["roster_ref"] == "research_team"
        assert briefs[0]["complexity_tier"] == "complex"
        assert briefs[0]["cost_ceiling_usd"] == 5.0
        assert briefs[0]["resolved_agent"] == "test.step_one.agent"
        assert briefs[0]["dependencies"] == []

        assert briefs[1]["step_id"] == "step-two"
        assert briefs[1]["roster_ref"] == "content_team"
        assert briefs[1]["complexity_tier"] == "simple"
        assert len(briefs[1]["dependencies"]) == 1
        assert briefs[1]["dependencies"][0]["depends_on_step"] == "step-one"


class TestWorkflowMatching:
    def test_match_by_pattern(self):
        service = WorkflowService(agent_registry={})
        workflow = _make_workflow(
            workflow_name="test.digest.workflow",
            trigger={
                "type": "on_demand",
                "match_patterns": ["ai news", "ai digest"],
            },
        )
        service._workflows = {"test.digest.workflow": workflow}

        result = service.match_workflow("Show me the latest ai news")
        assert result is not None
        assert result.workflow_name == "test.digest.workflow"

    def test_no_match(self):
        service = WorkflowService(agent_registry={})
        service._workflows = {}

        result = service.match_workflow("Tell me about the weather")
        assert result is None

    def test_disabled_workflow_not_matched(self):
        service = WorkflowService(agent_registry={})
        workflow = _make_workflow(
            workflow_name="test.disabled.workflow",
            enabled=False,
            trigger={
                "type": "on_demand",
                "match_patterns": ["test"],
            },
        )
        service._workflows = {"test.disabled.workflow": workflow}

        result = service.match_workflow("test something")
        assert result is None

    def test_case_insensitive_matching(self):
        service = WorkflowService(agent_registry={})
        workflow = _make_workflow(
            trigger={
                "type": "on_demand",
                "match_patterns": ["AI News"],
            },
        )
        service._workflows = {"test.example.workflow": workflow}

        result = service.match_workflow("give me ai news please")
        assert result is not None


class TestUpstreamContextResolution:
    def test_resolve_context_references(self):
        service = WorkflowService(agent_registry={})
        step = WorkflowSchema(
            workflow_name="test.ctx.workflow",
            description="Test context",
            objective={
                "statement": "T", "category": "t",
                "owner": "t", "priority": "low",
            },
            steps=[
                {"id": "step-a", "capability": "test.agent"},
                {
                    "id": "step-b", "capability": "test.agent",
                    "depends_on": ["step-a"],
                    "input": {
                        "articles": "@context.raw_articles",
                        "static": "hello",
                    },
                },
            ],
        ).steps[1]

        completed_outcomes = {
            "step-a": {"raw_articles": ["article1", "article2"]},
        }

        result = service.resolve_upstream_context(
            step, completed_outcomes, {"base_key": "base_value"},
        )

        assert result["base_key"] == "base_value"
        assert result["raw_articles"] == ["article1", "article2"]
        assert result["_step_input"]["articles"] == ["article1", "article2"]
        assert result["_step_input"]["static"] == "hello"

    def test_unresolved_reference_raises(self):
        """Unresolved @context.* references raise ValueError (P0.3)."""
        service = WorkflowService(agent_registry={})
        step = WorkflowSchema(
            workflow_name="test.unresolved.workflow",
            description="Test",
            objective={
                "statement": "T", "category": "t",
                "owner": "t", "priority": "low",
            },
            steps=[
                {
                    "id": "step-a", "capability": "test.agent",
                    "input": {"data": "@context.missing_key"},
                },
            ],
        ).steps[0]

        with pytest.raises(ValueError, match="unresolvable @context reference"):
            service.resolve_upstream_context(step, {}, {})


class TestWorkflowLoading:
    def test_load_from_directory(self, tmp_path):
        """Load workflows from a tmp directory via config override."""
        workflows_dir = tmp_path / "workflow_templates"
        workflows_dir.mkdir()

        workflow_data = {
            "workflow_name": "test.loaded.workflow",
            "description": "Loaded from disk",
                "objective": {
                "statement": "Test loading",
                "category": "testing",
                "owner": "test",
                "priority": "normal",
            },
            "steps": [
                {"id": "step-one", "capability": "test.agent"},
            ],
        }
        (workflows_dir / "test.yaml").write_text(yaml.dump(workflow_data))

        service = WorkflowService(agent_registry={})
        service._project_root = tmp_path

        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.workflows.workflows_dir = "workflow_templates"
        mock_config.workflows.max_steps_per_workflow = 20
        mock_config.workflows.max_budget_usd = 100.0

        with patch(
            "modules.backend.services.workflow.get_app_config",
            return_value=mock_config,
        ):
            loaded = service.load_workflows()

        assert "test.loaded.workflow" in loaded
        assert loaded["test.loaded.workflow"].description == "Loaded from disk"

    def test_list_workflows_enabled_only(self):
        service = WorkflowService(agent_registry={})
        service._workflows = {
            "enabled": _make_workflow(
                workflow_name="test.enabled.workflow", enabled=True,
            ),
            "disabled": _make_workflow(
                workflow_name="test.disabled.workflow", enabled=False,
            ),
        }

        enabled = service.list_workflows(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].workflow_name == "test.enabled.workflow"

    def test_list_workflows_all(self):
        service = WorkflowService(agent_registry={})
        service._workflows = {
            "enabled": _make_workflow(
                workflow_name="test.enabled.workflow", enabled=True,
            ),
            "disabled": _make_workflow(
                workflow_name="test.disabled.workflow", enabled=False,
            ),
        }

        all_workflows = service.list_workflows(enabled_only=False)
        assert len(all_workflows) == 2

    def test_get_workflow(self):
        service = WorkflowService(agent_registry={})
        workflow = _make_workflow()
        service._workflows = {"test.example.workflow": workflow}

        result = service.get_workflow("test.example.workflow")
        assert result is not None
        assert result.workflow_name == "test.example.workflow"

    def test_get_workflow_not_found(self):
        service = WorkflowService(agent_registry={})
        service._workflows = {}

        result = service.get_workflow("nonexistent")
        assert result is None
