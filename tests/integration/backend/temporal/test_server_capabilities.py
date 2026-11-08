"""Temporal server capability checks (Plan 88 step 88.0.1, contract 3.7 item 1).

Proves the configured Temporal server implements the RPCs later phases depend on:
``ListScheduleMatchingTimes`` (Phase 1 ``claim_occurrence``) and Workflow Update
(Phase 4 gate decisions). Cron times are never computed locally.
"""

from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from google.protobuf.timestamp_pb2 import Timestamp
from temporalio import workflow
from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.worker import Worker

# The workflow sandbox re-imports this module; pass application imports through,
# as every workflow module in modules/backend/temporal does.
with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal.client import get_temporal_client

_LONDON = ZoneInfo("Europe/London")


def _ts(value: datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(value)
    return ts


async def _matching_times(
    client: Client, schedule_id: str, start: datetime, end: datetime
) -> list[datetime]:
    response = await client.workflow_service.list_schedule_matching_times(
        ListScheduleMatchingTimesRequest(
            namespace=client.namespace,
            schedule_id=schedule_id,
            start_time=_ts(start),
            end_time=_ts(end),
        )
    )
    return [t.ToDatetime(tzinfo=timezone.utc) for t in response.start_time]


async def _create_probe(client: Client, schedule_id: str, cron: str) -> None:
    await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "P88CapabilityProbe", id=f"{schedule_id}-wf", task_queue=f"{schedule_id}-q"
            ),
            spec=ScheduleSpec(cron_expressions=[cron], time_zone_name="Europe/London"),
            state=ScheduleState(paused=True),
        ),
    )


def _probe_schedule_id() -> str:
    return f"p88-capability-probe-{uuid4().hex[:8]}"


@workflow.defn(name="P88UpdateProbe")
class UpdateProbeWorkflow:
    def __init__(self) -> None:
        self._done = False

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self._done)
        return "done"

    @workflow.update
    async def finish(self, value: str) -> str:
        self._done = True
        return value


async def test_list_schedule_matching_times_supported() -> None:
    client = await get_temporal_client()
    schedule_id = _probe_schedule_id()
    await _create_probe(client, schedule_id, "0 * * * *")
    try:
        times = await _matching_times(
            client,
            schedule_id,
            datetime(2027, 1, 15, 0, 30, tzinfo=timezone.utc),
            datetime(2027, 1, 16, 0, 30, tzinfo=timezone.utc),
        )
    finally:
        await client.get_schedule_handle(schedule_id).delete()

    assert len(times) == 24
    assert all(t.astimezone(_LONDON).minute == 0 for t in times)


async def test_schedule_time_zone_name_respected() -> None:
    client = await get_temporal_client()
    schedule_id = _probe_schedule_id()
    await _create_probe(client, schedule_id, "0 6 * * *")
    try:
        winter = await _matching_times(
            client,
            schedule_id,
            datetime(2027, 1, 15, 0, 0, tzinfo=timezone.utc),
            datetime(2027, 1, 16, 0, 0, tzinfo=timezone.utc),
        )
        summer = await _matching_times(
            client,
            schedule_id,
            datetime(2027, 7, 15, 0, 0, tzinfo=timezone.utc),
            datetime(2027, 7, 16, 0, 0, tzinfo=timezone.utc),
        )
    finally:
        await client.get_schedule_handle(schedule_id).delete()

    assert winter == [datetime(2027, 1, 15, 6, 0, tzinfo=timezone.utc)]
    assert summer == [datetime(2027, 7, 15, 5, 0, tzinfo=timezone.utc)]


async def test_workflow_update_supported() -> None:
    client = await get_temporal_client()
    q = f"p88-update-probe-{uuid4().hex[:8]}"
    async with Worker(client, task_queue=q, workflows=[UpdateProbeWorkflow]):
        handle = await client.start_workflow(UpdateProbeWorkflow.run, id=f"{q}-wf", task_queue=q)
        assert await handle.execute_update(UpdateProbeWorkflow.finish, "ok") == "ok"
        assert await handle.result() == "done"
