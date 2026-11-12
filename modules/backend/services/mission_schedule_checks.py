"""Mission schedule validation and Temporal schedule construction (Plan 88 step 88.1.6).

Split from services/mission_schedule.py to keep it under 500 lines. Every
create- and update-time rule of MissionScheduleService that is not a status
transition lives here, with the only builders of the spec and Schedule that
sync_to_temporal registers (contract 3.3.2).
"""

import string
from datetime import datetime, timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema_missions import RecurrenceSchema
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.models.mission_schedule import MissionSchedule, MissionScheduleKind
from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository
from modules.backend.schemas.mission_schedule import MissionScheduleUpdate
from modules.backend.schemas.workflow import WorkflowParameterSchema, WorkflowStepSchema
from modules.backend.services.workflow_run import validate_workflow_parameters
from modules.backend.temporal.mission_run_models import MissionScheduleTickInput, TickConfigSnapshot
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway

PROBE_WINDOW = timedelta(days=8)
TEMPLATE_PLACEHOLDERS = frozenset({"scheduled_for", "sequence", "mission_name"})
_SCHEDULABLE_NODE_TYPE = "agent_step"
# The tick workflow is registered by 88.1.8 under its class name.
TICK_WORKFLOW_TYPE = "MissionScheduleTickWorkflow"
TICK_WORKFLOW_ID_PREFIX = "mission-tick-"


def build_spec(
    cron_expression: str,
    time_zone_name: str,
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> ScheduleSpec:
    """The only ScheduleSpec builder for mission schedules (contract 3.3.2)."""
    return ScheduleSpec(
        cron_expressions=[cron_expression],
        time_zone_name=time_zone_name,
        start_at=starts_at,
        end_at=ends_at,
    )


def build_tick_schedule(
    schedule_id: str,
    snapshot: TickConfigSnapshot,
    spec: ScheduleSpec,
    catch_up_window_seconds: int,
    paused: bool,
    note: str,
) -> Schedule:
    """The Temporal Schedule for one mission_schedules row (contract 3.3.2).

    The tick's execution timeout spans the catch-up window plus the run time, so a
    tick Temporal starts while the worker is down survives until the worker returns
    and claims its slot as MISSED or SUPERSEDED instead of timing out unrecorded.
    """
    run_timeout = get_app_config().temporal.mission_run.tick_execution_timeout_seconds
    timeout = catch_up_window_seconds + run_timeout
    return Schedule(
        action=ScheduleActionStartWorkflow(
            TICK_WORKFLOW_TYPE,
            MissionScheduleTickInput(mission_schedule_id=schedule_id, config=snapshot),
            id=f"{TICK_WORKFLOW_ID_PREFIX}{schedule_id}",
            task_queue=snapshot.task_queue,
            execution_timeout=timedelta(seconds=timeout),
        ),
        spec=spec,
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.ALLOW_ALL,
            catchup_window=timedelta(seconds=catch_up_window_seconds),
            pause_on_failure=False,
        ),
        state=ScheduleState(paused=paused, note=note),
    )


async def probe_spec(
    gateway: TemporalScheduleGateway, spec: ScheduleSpec, recurrence: RecurrenceSchema
) -> None:
    """Validate the spec on the server and reject cron firing more often than allowed."""
    times = sorted(await gateway.validate_spec(spec, window=PROBE_WINDOW))
    minimum = recurrence.min_interval_seconds
    for earlier, later in zip(times, times[1:]):
        gap = int((later - earlier).total_seconds())
        if gap < minimum:
            raise ValidationError(f"cron fires every {gap}s; minimum {minimum}s")


def check_template(template: str | None, recurrence: RecurrenceSchema) -> None:
    """Length limit, and only the allowed placeholders with no format spec or conversion."""
    if not template:
        raise ValidationError("objective_template is required")
    if len(template) > recurrence.objective_template_max_chars:
        raise ValidationError(
            f"objective_template exceeds {recurrence.objective_template_max_chars} characters"
        )
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as err:
        raise ValidationError(f"objective_template is malformed: {err}") from err
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in TEMPLATE_PLACEHOLDERS or format_spec or conversion:
            raise ValidationError(
                f"objective_template placeholder {{{field_name}}} is not allowed; "
                f"use {sorted(TEMPLATE_PLACEHOLDERS)} with no format spec or conversion"
            )


def resolve_catch_up(value: int | None, recurrence: RecurrenceSchema) -> int:
    """The requested catch-up window, or the configured default, within the maximum."""
    catch_up = value if value is not None else recurrence.default_catch_up_window_seconds
    if catch_up > recurrence.max_catch_up_window_seconds:
        raise ValidationError(
            f"catch_up_window_seconds exceeds {recurrence.max_catch_up_window_seconds}"
        )
    return catch_up


async def check_definition(
    definitions: WorkflowDefinitionRepository,
    mission_id: str,
    definition_id: str | None,
    parameters: dict,
) -> None:
    """The definition is the mission's or a system template, enabled, agent steps only."""
    if definition_id is None:
        raise ValidationError("workflow_definition_id is required")
    definition = await definitions.get_by_id_or_none(definition_id)
    if definition is None or definition.mission_id not in (mission_id, None):
        raise NotFoundError(f"Workflow definition {definition_id} not found")
    if not definition.enabled:
        raise ValidationError(f"workflow definition {definition.name} is disabled")
    steps = [WorkflowStepSchema(**step) for step in definition.steps]
    offending = [step.id for step in steps if step.node_type != _SCHEDULABLE_NODE_TYPE]
    if offending:
        raise ValidationError(
            f"only agent_step workflows can be scheduled; offending steps: {offending}"
        )
    errors = validate_workflow_parameters(
        [WorkflowParameterSchema(**p) for p in definition.parameters], parameters
    )
    if errors:
        raise ValidationError(f"invalid workflow parameters: {errors}")


async def check_update_target(
    definitions: WorkflowDefinitionRepository,
    mission_id: str,
    schedule: MissionSchedule,
    data: MissionScheduleUpdate,
    present: set[str],
    recurrence: RecurrenceSchema,
) -> None:
    """Target fields present in an update must match the schedule's immutable kind."""
    workflow_fields = present & {"workflow_definition_id", "workflow_parameters"}
    if schedule.kind == MissionScheduleKind.OBJECTIVE:
        if workflow_fields:
            raise ValidationError("an objective schedule has no workflow fields")
        if "objective_template" in present:
            check_template(data.objective_template, recurrence)
        return
    if "objective_template" in present:
        raise ValidationError("a workflow_definition schedule has no objective_template")
    if workflow_fields:
        definition_id = (
            data.workflow_definition_id
            if "workflow_definition_id" in present
            else schedule.workflow_definition_id
        )
        parameters = (
            data.workflow_parameters
            if "workflow_parameters" in present
            else schedule.workflow_parameters
        )
        await check_definition(definitions, mission_id, definition_id, parameters)
