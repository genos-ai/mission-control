"""Tests for Temporal Activities.

send_notification is tested live (it's a stub that logs).
execute_mission mocks handle_mission (LLM calls — not infra we operate).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.temporal.models import MissionWorkflowInput, NotificationPayload


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_returns_true(self):
        """send_notification is a logging stub — test it live."""
        from modules.backend.temporal.activities import send_notification

        result = await send_notification(
            NotificationPayload(
                channel="webhook",
                recipient="admin",
                title="Test",
                body="Test body",
                action_url="/test",
            ),
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_handles_all_urgency_levels(self):
        from modules.backend.temporal.activities import send_notification

        for urgency in ("low", "normal", "high", "critical"):
            result = await send_notification(
                NotificationPayload(
                    channel="slack",
                    recipient="team",
                    title="Alert",
                    body="Body",
                    action_url="/url",
                    urgency=urgency,
                ),
            )
            assert result is True


def _mock_db_session_ctx(mock_session):
    """Build an async context manager that yields mock_session."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _ctx():
        yield mock_session

    return _ctx


class TestExecuteMission:
    def _patch_infra(self, dispatch_return=None, dispatch_side_effect=None):
        """Return a context manager that patches Redis, DB, MissionService, and Orchestrator."""
        from contextlib import AsyncExitStack

        mock_session = AsyncMock()
        mock_mission = MagicMock()
        mock_mission.owner_id = "owner-uuid"

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        patches = {}

        patches["redis_url"] = patch(
            "modules.backend.core.config.get_redis_url",
            return_value="redis://localhost:6379/1",
        )
        patches["redis_cls"] = patch(
            "redis.asyncio.Redis.from_url",
            return_value=mock_redis,
        )
        patches["get_session"] = patch(
            "modules.backend.core.database.get_async_session",
            side_effect=_mock_db_session_ctx(mock_session),
        )
        patches["mission_svc"] = patch(
            "modules.backend.services.mission.MissionService",
        )
        patches["orchestrator"] = patch(
            "modules.backend.services.mission_plan_orchestrator.MissionPlanOrchestrator",
        )
        patches["event_bus"] = patch(
            "modules.backend.events.bus.SessionEventBus",
        )
        patches["heartbeat"] = patch(
            "modules.backend.temporal.activities.activity.heartbeat",
        )
        patches["activity_info"] = patch(
            "modules.backend.temporal.activities.activity.info",
            return_value=MagicMock(workflow_id="mission-run-test"),
        )

        class _Ctx:
            async def __aenter__(self_ctx):
                self_ctx._stack = AsyncExitStack()
                await self_ctx._stack.__aenter__()
                entered = {}
                for name, p in patches.items():
                    entered[name] = self_ctx._stack.enter_context(p)

                # MissionService().get_mission() returns mock_mission
                entered["mission_svc"].return_value.get_mission = AsyncMock(
                    return_value=mock_mission,
                )

                # MissionPlanOrchestrator().dispatch_approved() returns result
                mock_dispatch = AsyncMock()
                if dispatch_side_effect:
                    mock_dispatch.side_effect = dispatch_side_effect
                elif dispatch_return is not None:
                    mock_dispatch.return_value = dispatch_return
                else:
                    mock_dispatch.return_value = {}
                entered["orchestrator"].return_value.dispatch_approved = mock_dispatch

                return entered

            async def __aexit__(self_ctx, *args):
                await self_ctx._stack.__aexit__(*args)

        return _Ctx()

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        """Mock dispatch_approved (LLM calls) but test the Activity logic live."""
        from modules.backend.temporal.activities import execute_mission

        dispatch_result = {
            "outcome_status": "completed",
            "total_cost_usd": 0.05,
            "dispatched_task_ids": [],
            "updated_task_ids": [],
        }

        async with self._patch_infra(dispatch_return=dispatch_result):
            result = await execute_mission(
                MissionWorkflowInput(
                    mission_run_id="test-1",
                    session_id="5714117c-eaed-5ce3-9c56-73949f03aa3d",
                    mission_brief="Test mission",
                    mission_id="00000000-0000-0000-0000-000000000001",
                ),
            )

            assert result.status == "completed"
            assert result.mission_id == "test-1"
            assert result.total_cost_usd == 0.05
            assert result.task_count == 0

    @pytest.mark.asyncio
    async def test_counts_task_results(self):
        from modules.backend.temporal.activities import execute_mission

        dispatch_result = {
            "outcome_status": "partial",
            "total_cost_usd": 0.10,
            "dispatched_task_ids": ["t1", "t2"],
            "updated_task_ids": ["t1"],
        }

        async with self._patch_infra(dispatch_return=dispatch_result):
            result = await execute_mission(
                MissionWorkflowInput(
                    mission_run_id="test-2",
                    session_id="bac9134a-a913-50f4-adec-9725086b8998",
                    mission_brief="Partial mission",
                    mission_id="00000000-0000-0000-0000-000000000002",
                ),
            )

            assert result.status == "partial"
            assert result.task_count == 2
            assert result.success_count == 1

    @pytest.mark.asyncio
    async def test_execute_mission_reraises_cancelled_error(self):
        from modules.backend.temporal.activities import execute_mission

        async with self._patch_infra(dispatch_side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await execute_mission(
                    MissionWorkflowInput(
                        mission_run_id="test-3",
                        session_id="80d00060-470d-5db0-aa70-5adc526200ea",
                        mission_brief="Cancelled mission",
                        mission_id="00000000-0000-0000-0000-000000000003",
                    ),
                )

    @pytest.mark.asyncio
    async def test_execute_mission_reraises_dispatch_exception(self):
        from modules.backend.events.types import SystemEvent
        from modules.backend.temporal.activities import execute_mission

        async with self._patch_infra(dispatch_side_effect=RuntimeError("boom")) as entered:
            publish = AsyncMock()
            entered["event_bus"].return_value.publish_to_mission = publish
            with pytest.raises(RuntimeError, match="boom"):
                await execute_mission(
                    MissionWorkflowInput(
                        mission_run_id="test-4",
                        session_id="80d00060-470d-5db0-aa70-5adc526200ea",
                        mission_brief="Failing mission",
                        mission_id="00000000-0000-0000-0000-000000000004",
                    ),
                )

            publish.assert_awaited_once()
            event = publish.await_args.args[1]
            assert isinstance(event, SystemEvent)
            assert event.level == "error"

    @pytest.mark.asyncio
    async def test_execute_mission_heartbeats_while_dispatching(self):
        from modules.backend.temporal.activities import execute_mission

        async def _slow_dispatch(*args, **kwargs):
            await asyncio.sleep(0.05)
            return {}

        app_config = MagicMock()
        app_config.temporal.mission_run.task_heartbeat_interval_seconds = 0.01

        async with self._patch_infra(dispatch_side_effect=_slow_dispatch) as entered:
            with patch(
                "modules.backend.core.config.get_app_config",
                return_value=app_config,
            ):
                await execute_mission(
                    MissionWorkflowInput(
                        mission_run_id="test-5",
                        session_id="80d00060-470d-5db0-aa70-5adc526200ea",
                        mission_brief="Slow mission",
                        mission_id="00000000-0000-0000-0000-000000000005",
                    ),
                )

            heartbeat = entered["heartbeat"]
            assert heartbeat.call_count >= 3
            for call in heartbeat.call_args_list:
                assert call.args == ({"phase": "dispatch"},)


class TestPersistMissionOutcome:
    @pytest.mark.asyncio
    async def test_persist_mission_outcome_reraises_on_failure(self):
        from modules.backend.temporal.activities import persist_mission_outcome

        with (
            patch(
                "modules.backend.core.database.get_async_session",
                side_effect=_mock_db_session_ctx(AsyncMock()),
            ),
            patch(
                "modules.backend.agents.mission_control.persistence_bridge.persist_mission_results",
                AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await persist_mission_outcome(
                    "run-1",
                    "80d00060-470d-5db0-aa70-5adc526200ea",
                    "default",
                    {"mission_id": "m-1", "status": "success"},
                    None,
                )
