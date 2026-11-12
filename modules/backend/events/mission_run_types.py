"""Mission run and schedule session events (Plan 88, contract 3.6.1).

Registered in EVENT_TYPE_MAP in events/types.py. Every event carries
mission_id and mission_run_id; status and reason fields carry lowercase enum
values. Error text is redacted with core.redaction.redact_secrets before it
is put in a payload.
"""

import uuid
from datetime import datetime

from modules.backend.events.base import SessionEvent
from modules.backend.schemas.execution_outcome import TaskResult


class MissionRunCreatedEvent(SessionEvent):
    """A mission run row was inserted as PENDING."""

    event_type: str = "mission_run.created"
    mission_id: str
    mission_run_id: str | None
    sequence: int
    trigger: str
    schedule_id: str | None
    scheduled_for: datetime | None


class MissionRunStatusChangedEvent(SessionEvent):
    """A mission run moved between statuses."""

    event_type: str = "mission_run.status_changed"
    mission_id: str
    mission_run_id: str | None
    from_status: str | None
    to_status: str
    reason: str | None
    detail: str | None


class MissionRunOccurrenceRecordedEvent(SessionEvent):
    """A schedule claim recorded SKIPPED or MISSED occurrences."""

    event_type: str = "mission_run.occurrence_recorded"
    mission_id: str
    mission_run_id: str | None
    status: str
    reason: str
    scheduled_for: datetime
    count: int


class MissionScheduleChangedEvent(SessionEvent):
    """A mission schedule changed status."""

    event_type: str = "mission_schedule.changed"
    mission_id: str
    mission_run_id: str | None
    schedule_id: str
    from_status: str | None
    to_status: str
    completed_reason: str | None


class MissionScheduleSyncFailedEvent(SessionEvent):
    """Mirroring a mission schedule to Temporal failed; error is redacted."""

    event_type: str = "mission_schedule.sync_failed"
    mission_id: str
    mission_run_id: str | None
    schedule_id: str
    error: str


class TaskFailedEvent(SessionEvent):
    """A task attempt failed; published once, after its record commits (display only)."""

    event_type: str = "task.failed"
    mission_id: str
    mission_run_id: str | None
    task_id: str
    agent_name: str
    origin: str
    failure_class: str
    fingerprint: str
    summary: str
    retryable: bool


class ContextCompactedEvent(SessionEvent):
    """The MCD was compacted at run end; published after the compaction commits."""

    event_type: str = "context.compacted"
    mission_id: str
    mission_run_id: str | None
    from_bytes: int
    to_bytes: int
    archived_paths: list[str]


def task_failed_event(
    result: TaskResult, *, mission_id: str, mission_run_id: str, session_id: str
) -> TaskFailedEvent:
    """The TaskFailedEvent for a failed TaskResult; its summary is already redacted (3.8.1)."""
    failure = result.failure
    if failure is None:
        raise ValueError(f"TaskResult {result.task_id} carries no failure")
    return TaskFailedEvent(
        session_id=uuid.UUID(session_id),
        source="execute_plan_task",
        mission_id=mission_id,
        mission_run_id=mission_run_id,
        task_id=result.task_id,
        agent_name=result.agent_name,
        origin=failure.origin.value,
        failure_class=failure.failure_class.value,
        fingerprint=failure.fingerprint,
        summary=failure.summary,
        retryable=failure.retryable,
    )
