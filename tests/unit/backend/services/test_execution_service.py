"""
Tests for ExecutionService.

Uses real db_session with transaction rollback (P12).
Only mocks get_app_config (config loading — not infra we operate).
"""

import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config_schema import WorkflowsSchema
from modules.backend.models.execution import Execution, ExecutionState
from modules.backend.repositories.execution import ExecutionRepository
from modules.backend.services.execution import ExecutionService


def _mock_app_config(**overrides):
    config = MagicMock()
    config.workflows = WorkflowsSchema(**overrides)
    return config


@pytest.fixture
def execution_service(db_session: AsyncSession) -> ExecutionService:
    with patch(
        "modules.backend.services.execution.get_app_config",
        return_value=_mock_app_config(),
    ):
        return ExecutionService(session=db_session)


class TestCreateAdhocExecution:
    @pytest.mark.asyncio
    async def test_creates_execution(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Test objective",
                triggered_by="user:test",
                session_id="test-session-id",
            )

        assert execution.id is not None
        assert execution.objective == "Test objective"
        assert execution.status == ExecutionState.PENDING
        assert execution.roster_ref == "default"
        assert execution.complexity_tier == "simple"
        assert execution.triggered_by == "user:test"
        assert execution.trigger_type == "on_demand"
        assert execution.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_custom_roster_and_tier(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Complex task",
                triggered_by="user:test",
                session_id="test-session-id",
                roster_ref="research_team",
                complexity_tier="complex",
                cost_ceiling_usd=25.0,
            )

        assert execution.roster_ref == "research_team"
        assert execution.complexity_tier == "complex"
        assert execution.cost_ceiling_usd == 25.0

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(max_concurrent_missions=1),
        ):
            service = ExecutionService(session=db_session)

            # Create first execution (should succeed)
            await service.create_adhoc_execution(
                objective="First",
                triggered_by="user:test",
                session_id="sess-1",
            )

            # Second should fail due to concurrency limit
            from modules.backend.core.exceptions import ValidationError
            with pytest.raises(ValidationError, match="Maximum concurrent"):
                await service.create_adhoc_execution(
                    objective="Second",
                    triggered_by="user:test",
                    session_id="sess-2",
                )


class TestCreateExecutionFromStep:
    @pytest.mark.asyncio
    async def test_creates_from_step(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_execution_from_step(
                workflow_run_id="run-123",
                step_id="scrape",
                objective="Fetch articles",
                roster_ref="research_team",
                complexity_tier="simple",
                cost_ceiling_usd=0.50,
                upstream_context={"sources": ["url1"]},
                session_id="test-session-id",
            )

        assert execution.workflow_run_id == "run-123"
        assert execution.workflow_step_id == "scrape"
        assert execution.roster_ref == "research_team"
        assert execution.upstream_context == {"sources": ["url1"]}
        assert execution.trigger_type == "workflow"


class TestExecutionStateTransitions:
    @pytest.mark.asyncio
    async def test_pending_to_cancelled(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Cancellable",
                triggered_by="user:test",
                session_id="sess-1",
            )

            cancelled = await service.cancel_execution(
                execution.id, reason="Changed mind",
            )

        assert cancelled.status == ExecutionState.CANCELLED
        assert cancelled.error_data == {"cancelled_reason": "Changed mind"}
        assert cancelled.completed_at is not None

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Test",
                triggered_by="user:test",
                session_id="sess-1",
            )
            await service.cancel_execution(execution.id, reason="done")

            from modules.backend.core.exceptions import ValidationError
            with pytest.raises(ValidationError, match="Cannot transition"):
                await service.complete_execution(execution.id)

    @pytest.mark.asyncio
    async def test_complete_execution(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Complete me",
                triggered_by="user:test",
                session_id="sess-1",
            )

            # Transition to running first
            m = await service._get_execution(execution.id)
            m.status = ExecutionState.RUNNING
            m.started_at = "2026-01-01T00:00:00"
            await db_session.flush()

            completed = await service.complete_execution(execution.id)

        assert completed.status == ExecutionState.COMPLETED
        assert completed.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_execution(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Fail me",
                triggered_by="user:test",
                session_id="sess-1",
            )

            m = await service._get_execution(execution.id)
            m.status = ExecutionState.RUNNING
            await db_session.flush()

            failed = await service.fail_execution(
                execution.id, error="Something went wrong",
            )

        assert failed.status == ExecutionState.FAILED
        assert failed.error_data == {"message": "Something went wrong"}


class TestOutputExtraction:
    @pytest.mark.asyncio
    async def test_extract_summary_key(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Extract test",
                triggered_by="user:test",
                session_id="sess-1",
            )
            execution.execution_outcome = {"summary": "All done"}
            await db_session.flush()

        output_mapping = {"summary_key": "result"}
        extracted = service.extract_outputs(execution, output_mapping)
        assert extracted == {"result": "All done"}

    @pytest.mark.asyncio
    async def test_extract_field_mappings(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = await service.create_adhoc_execution(
                objective="Extract fields",
                triggered_by="user:test",
                session_id="sess-1",
            )
            execution.execution_outcome = {
                "task_results": {
                    "scrape_articles": {"articles": ["a1", "a2"]},
                },
            }
            await db_session.flush()

        output_mapping = {
            "field_mappings": [
                {
                    "source_task": "scrape_articles",
                    "source_field": "articles",
                    "target_key": "raw_articles",
                },
            ],
        }
        extracted = service.extract_outputs(execution, output_mapping)
        assert extracted == {"raw_articles": ["a1", "a2"]}

    def test_extract_no_mapping(self, db_session: AsyncSession):
        service = ExecutionService(session=db_session)
        execution = MagicMock()
        execution.execution_outcome = {"summary": "test"}
        assert service.extract_outputs(execution, None) == {}

    def test_extract_no_outcome(self, db_session: AsyncSession):
        service = ExecutionService(session=db_session)
        execution = MagicMock()
        execution.execution_outcome = None
        assert service.extract_outputs(execution, {"summary_key": "r"}) == {}


class TestListAndGetExecutions:
    @pytest.mark.asyncio
    async def test_list_executions(self, db_session: AsyncSession):
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            await service.create_adhoc_execution(
                objective="Execution 1",
                triggered_by="user:test",
                session_id="sess-1",
            )
            await service.create_adhoc_execution(
                objective="Execution 2",
                triggered_by="user:test",
                session_id="sess-2",
            )

            executions, total = await service.list_executions()

        assert total == 2
        assert len(executions) == 2

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, db_session: AsyncSession):
        service = ExecutionService(session=db_session)

        from modules.backend.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await service.get_execution("nonexistent-id")


class TestExtractOutputs:
    """P0.5: extract_outputs reliability fixes."""

    def _make_execution(self, outcome=None):
        execution = MagicMock()
        execution.id = "test-execution"
        execution.execution_outcome = outcome
        execution.result_summary = "Test summary"
        return execution

    def test_no_output_mapping_returns_empty(self, db_session: AsyncSession):
        """Returns {} and logs debug when output_mapping is None."""
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = self._make_execution(outcome={"task_results": []})
            result = service.extract_outputs(execution, None)
            assert result == {}

    def test_no_outcome_returns_empty(self, db_session: AsyncSession):
        """Returns {} and logs warning when execution has no outcome."""
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = self._make_execution(outcome=None)
            result = service.extract_outputs(execution, {"field_mappings": []})
            assert result == {}

    def test_duplicate_agents_both_accessible(self, db_session: AsyncSession):
        """Multiple tasks with same agent_name are all searchable."""
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            execution = self._make_execution(outcome={
                "task_results": [
                    {
                        "task_id": "task-001",
                        "agent_name": "software.quality.agent",
                        "output_reference": {"report": "first report"},
                    },
                    {
                        "task_id": "task-002",
                        "agent_name": "software.quality.agent",
                        "output_reference": {"analysis": "second analysis"},
                    },
                ],
            })
            mapping = {
                "field_mappings": [
                    {
                        "source_task": "software.quality.agent",
                        "source_field": "analysis",
                        "target_key": "qa_analysis",
                    },
                ],
            }
            result = service.extract_outputs(execution, mapping)
            # Should find 'analysis' from the second entry, not be overwritten
            assert result["qa_analysis"] == "second analysis"
