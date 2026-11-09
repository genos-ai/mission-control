"""Mission run and schedule session events (Plan 88, contract 3.6.1).

Registered in EVENT_TYPE_MAP in events/types.py. Every event carries
mission_id and mission_run_id; status and reason fields carry lowercase enum
values. Error text is redacted with core.redaction.redact_secrets before it
is put in a payload.
"""

from datetime import datetime

from modules.backend.events.base import SessionEvent


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
