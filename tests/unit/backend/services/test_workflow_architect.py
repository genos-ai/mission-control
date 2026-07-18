"""Tests for the WorkflowArchitectService."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.agents.deps.base import FileScope
from modules.backend.services.workflow_architect import (
    ARCHITECT_AGENT_NAME,
    WorkflowArchitectService,
)


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def service(mock_session):
    return WorkflowArchitectService(mock_session)


def _mock_registry() -> MagicMock:
    """Registry mock: .get() returns agent config, .get_instance() the agent."""
    registry = MagicMock()
    registry.get.return_value = MagicMock(model="copilot:test-model")
    registry.get_instance.return_value = MagicMock()
    return registry


def _common_deps() -> dict:
    """Stand-in for build_deps_from_config() output."""
    return {
        "project_root": Path("/project"),
        "scope": FileScope(read_paths=[], write_paths=[]),
        "config": None,
    }


class TestWorkflowArchitectService:
    """Tests for WorkflowArchitectService.chat()."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.workflow_architect.run_conversational")
    @patch("modules.backend.services.workflow_architect.build_deps_from_config")
    @patch("modules.backend.services.workflow_architect._build_model")
    @patch("modules.backend.services.workflow_architect.get_registry")
    async def test_chat_returns_response(
        self,
        mock_registry,
        mock_build_model,
        mock_build_deps,
        mock_run_conv,
        service,
    ):
        registry = _mock_registry()
        mock_registry.return_value = registry
        mock_build_model.return_value = MagicMock()
        mock_build_deps.return_value = _common_deps()

        mock_run_conv.return_value = {
            "response": "I'll design a workflow for you.",
            "usage": None,
            "all_messages": [],
        }

        with patch.object(service, "_load_mission_context", new_callable=AsyncMock) as mock_ctx:
            mock_ctx.return_value = ("Review all modules", "- qa.agent: reviews code")

            result = await service.chat(
                mission_id="m-001",
                message="Design a review workflow",
            )

        assert result["response"] == "I'll design a workflow for you."
        mock_run_conv.assert_called_once()
        # Agent comes from the registry instance cache, built with the config model
        registry.get_instance.assert_called_once_with(
            ARCHITECT_AGENT_NAME,
            mock_build_model.return_value,
        )

    @pytest.mark.asyncio
    @patch("modules.backend.services.workflow_architect.run_conversational")
    @patch("modules.backend.services.workflow_architect.build_deps_from_config")
    @patch("modules.backend.services.workflow_architect._build_model")
    @patch("modules.backend.services.workflow_architect.get_registry")
    async def test_chat_enriches_first_message(
        self,
        mock_registry,
        mock_build_model,
        mock_build_deps,
        mock_run_conv,
        service,
    ):
        mock_registry.return_value = _mock_registry()
        mock_build_model.return_value = MagicMock()
        mock_build_deps.return_value = _common_deps()
        mock_run_conv.return_value = {"response": "ok", "usage": None, "all_messages": []}

        with patch.object(service, "_load_mission_context", new_callable=AsyncMock) as mock_ctx:
            mock_ctx.return_value = ("Mission brief text", "- agent.one: does things")

            await service.chat(
                mission_id="m-002",
                message="Help me design",
            )

        call_args = mock_run_conv.call_args
        enriched_message = call_args.args[2]
        assert "Mission Brief" in enriched_message
        assert "Mission brief text" in enriched_message
        assert "Current Team" in enriched_message

    @pytest.mark.asyncio
    @patch("modules.backend.services.workflow_architect.run_conversational")
    @patch("modules.backend.services.workflow_architect.build_deps_from_config")
    @patch("modules.backend.services.workflow_architect._build_model")
    @patch("modules.backend.services.workflow_architect.get_registry")
    async def test_chat_with_history_skips_enrichment(
        self,
        mock_registry,
        mock_build_model,
        mock_build_deps,
        mock_run_conv,
        service,
    ):
        mock_registry.return_value = _mock_registry()
        mock_build_model.return_value = MagicMock()
        mock_build_deps.return_value = _common_deps()
        mock_run_conv.return_value = {"response": "revised", "usage": None, "all_messages": []}

        existing_history = [MagicMock()]

        with patch.object(service, "_load_mission_context", new_callable=AsyncMock) as mock_ctx:
            mock_ctx.return_value = ("brief", "team")

            await service.chat(
                mission_id="m-003",
                message="Make it simpler",
                message_history=existing_history,
            )

        call_args = mock_run_conv.call_args
        raw_message = call_args.args[2]
        assert "Mission Brief" not in raw_message
        assert raw_message == "Make it simpler"


class TestBuildInitialPrompt:
    """Tests for _build_initial_prompt."""

    def test_includes_brief_and_team(self):
        svc = WorkflowArchitectService(AsyncMock())
        result = svc._build_initial_prompt(
            "Design a pipeline",
            "Optimize code quality",
            "- qa.agent: code reviewer",
        )
        assert "Design a pipeline" in result
        assert "Mission Brief" in result
        assert "Optimize code quality" in result
        assert "Current Team" in result
        assert "qa.agent" in result

    def test_empty_brief_omits_section(self):
        svc = WorkflowArchitectService(AsyncMock())
        result = svc._build_initial_prompt("hi", "", "- agent: desc")
        assert "Mission Brief" not in result
        assert "Current Team" in result

    def test_prompt_suffix(self):
        svc = WorkflowArchitectService(AsyncMock())
        result = svc._build_initial_prompt("start", "brief", "team")
        assert "browsing the agent catalog" in result
