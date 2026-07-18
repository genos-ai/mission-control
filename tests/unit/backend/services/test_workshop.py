"""Tests for the WorkshopService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.services.workshop import WORKSHOP_CATEGORY, WorkshopService


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def service(mock_session):
    return WorkshopService(mock_session)


class TestRunAgent:
    """Tests for WorkshopService.run_agent."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.workshop.get_app_config")
    @patch("modules.backend.services.workshop.get_registry")
    @patch("modules.backend.services.workshop._import_agent_module")
    @patch("modules.backend.services.workshop._build_model")
    @patch("modules.backend.services.workshop._build_agent_deps")
    @patch("modules.backend.services.workshop._get_usage_limits")
    @patch("modules.backend.services.workshop.compute_cost_usd")
    async def test_run_agent_basic(
        self,
        mock_cost,
        mock_limits,
        mock_deps,
        mock_build_model,
        mock_import,
        mock_registry,
        mock_app_config,
        service,
    ):
        mock_workshop_config = MagicMock()
        mock_workshop_config.default_budget_usd = 2.0
        mock_workshop_config.max_budget_usd = 20.0
        mock_app_config.return_value.workflows.workshop = mock_workshop_config

        mock_agent_config = MagicMock()
        mock_agent_config.model = "anthropic:claude-opus-4-20250514"
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_agent_config
        mock_registry.return_value = mock_reg

        mock_module = MagicMock()
        mock_agent = MagicMock()
        mock_module.create_agent.return_value = mock_agent
        mock_import.return_value = mock_module

        mock_model = MagicMock()
        mock_build_model.return_value = mock_model

        mock_deps_instance = MagicMock()
        mock_deps.return_value = mock_deps_instance

        mock_limits.return_value = MagicMock()

        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.stream_text = MagicMock(return_value=AsyncIterMock([]))
        mock_stream.get_output = AsyncMock(return_value={"result": "test output"})
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_stream.usage = MagicMock(return_value=mock_usage)
        mock_agent.run_stream.return_value = mock_stream

        mock_cost.return_value = 0.01

        with patch.object(service, "_persist_workshop_run", new_callable=AsyncMock) as mock_persist:
            mock_record = MagicMock()
            mock_record.id = "rec-123"
            mock_persist.return_value = mock_record

            result = await service.run_agent(
                "code.qa.agent",
                inputs={"target": "modules/"},
            )

        assert result["execution_record_id"] == "rec-123"
        assert result["agent_name"] == "code.qa.agent"
        assert result["cost_usd"] == 0.01
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        mock_persist.assert_called_once()

    @pytest.mark.asyncio
    @patch("modules.backend.services.workshop.get_app_config")
    @patch("modules.backend.services.workshop.get_registry")
    async def test_run_agent_not_found(
        self,
        mock_registry,
        mock_app_config,
        service,
    ):
        mock_reg = MagicMock()
        mock_reg.get.return_value = None
        mock_registry.return_value = mock_reg

        mock_workshop = MagicMock()
        mock_workshop.default_budget_usd = 2.0
        mock_workshop.max_budget_usd = 20.0
        mock_app_config.return_value.workflows.workshop = mock_workshop

        from modules.backend.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError, match="not found"):
            await service.run_agent("nonexistent.agent")


class TestGetCachedInputs:
    """Tests for WorkshopService.get_cached_inputs."""

    @pytest.mark.asyncio
    @patch("modules.backend.services.workshop.get_app_config")
    async def test_returns_cached_entries(self, mock_app_config, service):
        mock_workshop = MagicMock()
        mock_workshop.max_cached_input_sets = 10
        mock_app_config.return_value.workflows.workshop = mock_workshop

        mock_task = MagicMock()
        mock_task.id = "te-1"
        mock_task.task_id = "task-001"
        mock_task.agent_name = "code.qa.agent"
        mock_task.output_data = {"summary": "all good"}
        mock_task.cost_usd = 0.05
        mock_task.created_at = "2026-03-20T12:00:00"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_task]
        service._session.execute = AsyncMock(return_value=mock_result)

        cached = await service.get_cached_inputs("code.qa.agent")

        assert len(cached) == 1
        assert cached[0]["task_execution_id"] == "te-1"
        assert cached[0]["output_data"] == {"summary": "all good"}


class TestListRuns:
    """Tests for WorkshopService.list_runs."""

    @pytest.mark.asyncio
    async def test_lists_workshop_runs(self, service):
        mock_record = MagicMock()
        mock_record.id = "rec-1"
        mock_record.objective_category = WORKSHOP_CATEGORY

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        service._session.execute = AsyncMock(return_value=mock_result)

        runs = await service.list_runs()

        assert len(runs) == 1
        assert runs[0].id == "rec-1"


class TestParseAgentPath:
    """Tests for _parse_agent_path static method."""

    def test_three_part_name(self):
        assert WorkshopService._parse_agent_path("system.planning.agent") == ("system", "planning")

    def test_two_part_name(self):
        assert WorkshopService._parse_agent_path("software.qa") == ("software", "qa")

    def test_single_part_name(self):
        assert WorkshopService._parse_agent_path("standalone") == ("standalone", "standalone")


class AsyncIterMock:
    """Mock for async iterators."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
