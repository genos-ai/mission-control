"""Mission schedule schemas (Plan 88 step 88.1.6, contracts 3.5.3 and 3.0.2).

Enum fields use the lowercase enum value on the wire. OccurrenceClaim is the
internal result of MissionScheduleService.claim_occurrence, not an API body.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.backend.models.mission_run import MissionRun
from modules.backend.models.mission_schedule import (
    MissionScheduleCompletedReason,
    MissionScheduleKind,
    MissionScheduleStatus,
    TemporalSyncState,
)
from modules.backend.temporal.mission_run_models import (
    MissionRunWorkflowInput,
    NotificationRequest,
)

_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


def _check_cron(value: str | None) -> str | None:
    if value is None:
        return value
    if value.strip().startswith("@"):
        raise ValueError("cron '@' forms are not supported; use 5 fields")
    if len(value.split()) != 5:
        raise ValueError("cron_expression must have exactly 5 whitespace-separated fields")
    return value


def _check_time_zone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"unknown IANA time zone {value!r}") from err
    return value


class MissionScheduleCreate(BaseModel):
    """POST /missions/{id}/schedules body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=_NAME_PATTERN)
    kind: MissionScheduleKind
    objective_template: str | None = None
    workflow_definition_id: str | None = None
    workflow_parameters: dict[str, Any] = Field(default_factory=dict)
    cron_expression: str = Field(..., max_length=100)
    time_zone_name: str = Field(..., max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_runs: int | None = Field(None, gt=0)
    catch_up_window_seconds: int | None = Field(None, gt=0)

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, value: str | None) -> str | None:
        return _check_cron(value)

    @field_validator("time_zone_name")
    @classmethod
    def _time_zone(cls, value: str | None) -> str | None:
        return _check_time_zone(value)

    @model_validator(mode="after")
    def _target_matches_kind(self) -> "MissionScheduleCreate":
        if self.kind == MissionScheduleKind.OBJECTIVE:
            if not self.objective_template or self.workflow_definition_id is not None:
                raise ValueError("kind objective needs objective_template and no workflow")
        elif self.workflow_definition_id is None or self.objective_template is not None:
            raise ValueError(
                "kind workflow_definition needs workflow_definition_id and no objective_template"
            )
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MissionScheduleUpdate(BaseModel):
    """PATCH /missions/{id}/schedules/{sid} body; every field optional, kind immutable."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, pattern=_NAME_PATTERN)
    objective_template: str | None = None
    workflow_definition_id: str | None = None
    workflow_parameters: dict[str, Any] | None = None
    cron_expression: str | None = Field(None, max_length=100)
    time_zone_name: str | None = Field(None, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_runs: int | None = Field(None, gt=0)
    catch_up_window_seconds: int | None = Field(None, gt=0)

    @field_validator("cron_expression")
    @classmethod
    def _cron(cls, value: str | None) -> str | None:
        return _check_cron(value)

    @field_validator("time_zone_name")
    @classmethod
    def _time_zone(cls, value: str | None) -> str | None:
        return _check_time_zone(value)


class MissionScheduleResponse(BaseModel):
    """A mission schedule, with its next fire times from Temporal."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    name: str
    kind: MissionScheduleKind
    objective_template: str | None
    workflow_definition_id: str | None
    workflow_parameters: dict[str, Any]
    cron_expression: str
    time_zone_name: str
    starts_at: datetime | None
    ends_at: datetime | None
    max_runs: int | None
    catch_up_window_seconds: int
    status: MissionScheduleStatus
    completed_reason: MissionScheduleCompletedReason | None
    executed_run_count: int
    last_claimed_scheduled_for: datetime | None
    temporal_schedule_id: str
    temporal_sync_state: TemporalSyncState
    temporal_synced_at: datetime | None
    temporal_sync_error: str | None
    tick_config_hash: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime
    next_fire_times: list[datetime] = Field(default_factory=list)


@dataclass
class OccurrenceClaim:
    """Result of claim_occurrence.

    outcome is "run", "skipped", "missed" or "duplicate". run is this slot's
    row (the existing row for duplicate). run_input is set for a RUN, and for
    a duplicate whose row is still PENDING, so the tick can start it.
    recorded holds every SKIPPED or MISSED row this claim inserted.
    mission_paused is True when a breached cap paused the mission (88.4.6):
    the caller syncs the mission's schedules after the commit.
    """

    outcome: str
    run: MissionRun | None
    run_input: MissionRunWorkflowInput | None
    notifications: list[NotificationRequest] = field(default_factory=list)
    recorded: list[MissionRun] = field(default_factory=list)
    mission_paused: bool = False
