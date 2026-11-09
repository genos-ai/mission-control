"""TemporalScheduleGateway (Plan 88 step 88.1.5, contract 3.3.1).

The only module, besides system_schedules.py, that calls the Temporal Schedule
APIs. Cron matching times always come from the server
(ListScheduleMatchingTimes); they are never computed locally.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from google.protobuf.timestamp_pb2 import Timestamp
from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
)
from temporalio.service import RPCError, RPCStatusCode

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.temporal.client import get_temporal_client

logger = get_logger(__name__)

PROBE_PREFIX = "mission-schedule-probe-"
_PROBE_WORKFLOW_TYPE = "MissionScheduleProbe"


def _timestamp(value: datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(value)
    return ts


class TemporalScheduleGateway:
    """The only module, besides system_schedules.py, that imports temporalio.client.Schedule*."""

    def __init__(self, client: Client, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    @classmethod
    async def create(cls) -> "TemporalScheduleGateway":
        """get_temporal_client() and get_app_config().temporal.task_queue."""
        client = await get_temporal_client()
        return cls(client, get_app_config().temporal.task_queue)

    async def upsert(self, schedule_id: str, schedule: Schedule) -> None:
        """Create the schedule, or replace it when it already exists."""
        try:
            await self._client.create_schedule(schedule_id, schedule)
            logger.info("Temporal schedule created", extra={"schedule_id": schedule_id})
        except ScheduleAlreadyRunningError:
            await self._client.get_schedule_handle(schedule_id).update(
                lambda _: ScheduleUpdate(schedule=schedule)
            )
            logger.info("Temporal schedule updated", extra={"schedule_id": schedule_id})

    async def set_paused(self, schedule_id: str, paused: bool, note: str) -> None:
        handle = self._client.get_schedule_handle(schedule_id)
        if paused:
            await handle.pause(note=note)
        else:
            await handle.unpause(note=note)

    async def delete(self, schedule_id: str) -> None:
        """Delete the schedule; a schedule that does not exist is not an error."""
        try:
            await self._client.get_schedule_handle(schedule_id).delete()
        except RPCError as err:
            if err.status != RPCStatusCode.NOT_FOUND:
                raise
            logger.debug("Temporal schedule already absent", extra={"schedule_id": schedule_id})

    async def describe(self, schedule_id: str) -> ScheduleDescription | None:
        """The schedule's description, or None when it does not exist."""
        try:
            return await self._client.get_schedule_handle(schedule_id).describe()
        except RPCError as err:
            if err.status != RPCStatusCode.NOT_FOUND:
                raise
            return None

    async def list_matching_times(
        self, schedule_id: str, start: datetime, end: datetime
    ) -> list[datetime]:
        """Server-computed action times in [start, end], as timezone-aware UTC datetimes."""
        response = await self._client.workflow_service.list_schedule_matching_times(
            ListScheduleMatchingTimesRequest(
                namespace=self._client.namespace,
                schedule_id=schedule_id,
                start_time=_timestamp(start),
                end_time=_timestamp(end),
            )
        )
        return [t.ToDatetime(tzinfo=timezone.utc) for t in response.start_time]

    async def list_ids(self, prefix: str | None) -> list[str]:
        """Every schedule id in the namespace, filtered on prefix when given."""
        ids: list[str] = []
        async for entry in await self._client.list_schedules():
            if prefix is None or entry.id.startswith(prefix):
                ids.append(entry.id)
        return ids

    async def validate_spec(self, spec: ScheduleSpec, window: timedelta) -> list[datetime]:
        """Validate spec on the server through a paused probe; return its times in window.

        The probe is paused, so its workflow type is never started and need not exist.
        Raises ValidationError when the server rejects the spec.
        """
        probe_id = f"{PROBE_PREFIX}{uuid4().hex}"
        probe = Schedule(
            action=ScheduleActionStartWorkflow(
                _PROBE_WORKFLOW_TYPE, id=f"{probe_id}-wf", task_queue=self._task_queue
            ),
            spec=spec,
            state=ScheduleState(paused=True),
        )
        try:
            await self._client.create_schedule(probe_id, probe)
            now = utc_now()
            return await self.list_matching_times(probe_id, now, now + window)
        except RPCError as err:
            if err.status != RPCStatusCode.INVALID_ARGUMENT:
                raise
            raise ValidationError(str(err.message)) from err
        finally:
            await self.delete(probe_id)
