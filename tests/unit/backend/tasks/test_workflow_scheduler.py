"""Tests for the workflow scheduler task."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

DB_SESSION_PATH = "modules.backend.core.database.get_async_session"
SCHEDULE_SVC_PATH = "modules.backend.services.workflow_schedule.WorkflowScheduleService"
RUN_SVC_PATH = "modules.backend.services.workflow_run.WorkflowRunService"
EXEC_SVC_PATH = "modules.backend.services.execution.ExecutionService"
NOTIFY_PATH = "modules.backend.tasks.workflow_scheduler._notify_schedule_failure"


def _mock_session_ctx(mock_session=None):
    """Create a mock async context manager for get_async_session."""
    if mock_session is None:
        mock_session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestEvaluateWorkflowSchedules:
    """Tests for the evaluate_workflow_schedules task."""

    @pytest.mark.asyncio
    async def test_no_due_schedules(self):
        from modules.backend.tasks.workflow_scheduler import evaluate_workflow_schedules

        with patch(DB_SESSION_PATH, return_value=_mock_session_ctx()), \
             patch(SCHEDULE_SVC_PATH) as mock_svc_cls:
            mock_svc_cls.return_value.evaluate_due_schedules = AsyncMock(return_value=[])

            result = await evaluate_workflow_schedules()

        assert result["status"] == "completed"
        assert result["schedules_evaluated"] == 0
        assert result["runs_created"] == 0

    @pytest.mark.asyncio
    async def test_fires_due_schedules(self):
        from modules.backend.tasks.workflow_scheduler import evaluate_workflow_schedules

        fired = [{
            "schedule_id": "s-1",
            "workflow_definition_id": "wd-1",
            "mission_id": "m-1",
            "budget_per_run_usd": 5.0,
            "fired_at": "2026-03-20T12:00:00",
        }]

        mock_run = MagicMock(id="run-1", status="completed")

        with patch(DB_SESSION_PATH, return_value=_mock_session_ctx()), \
             patch(SCHEDULE_SVC_PATH) as mock_sch_cls, \
             patch(RUN_SVC_PATH) as mock_run_cls, \
             patch(EXEC_SVC_PATH):
            mock_sch_cls.return_value.evaluate_due_schedules = AsyncMock(return_value=fired)
            mock_run_cls.return_value.run_workflow_from_definition = AsyncMock(return_value=mock_run)

            result = await evaluate_workflow_schedules()

        assert result["status"] == "completed"
        assert result["schedules_evaluated"] == 1
        assert result["runs_created"] == 1
        assert result["runs_failed"] == 0

    @pytest.mark.asyncio
    async def test_handles_run_failure(self):
        from modules.backend.tasks.workflow_scheduler import evaluate_workflow_schedules

        fired = [{
            "schedule_id": "s-1",
            "workflow_definition_id": "wd-1",
            "mission_id": "m-1",
            "budget_per_run_usd": None,
            "fired_at": "2026-03-20T12:00:00",
        }]

        with patch(DB_SESSION_PATH, return_value=_mock_session_ctx()), \
             patch(SCHEDULE_SVC_PATH) as mock_sch_cls, \
             patch(RUN_SVC_PATH) as mock_run_cls, \
             patch(EXEC_SVC_PATH), \
             patch(NOTIFY_PATH, new_callable=AsyncMock) as mock_notify:
            mock_sch_cls.return_value.evaluate_due_schedules = AsyncMock(return_value=fired)
            mock_run_cls.return_value.run_workflow_from_definition = AsyncMock(
                side_effect=ValueError("Workflow disabled"),
            )

            result = await evaluate_workflow_schedules()

        assert result["status"] == "completed"
        assert result["runs_created"] == 0
        assert result["runs_failed"] == 1
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_evaluation_error(self):
        from modules.backend.tasks.workflow_scheduler import evaluate_workflow_schedules

        error_ctx = AsyncMock()
        error_ctx.__aenter__ = AsyncMock(side_effect=ConnectionError("DB down"))
        error_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(DB_SESSION_PATH, return_value=error_ctx):
            result = await evaluate_workflow_schedules()

        assert result["status"] == "error"
        assert "DB down" in result["error"]
