"""
Mission-scoped workflow and schedule API endpoints.

Workflow listing, import, detail, and cron schedule management.
Includes the Workflow Architect chat endpoint.
Split from missions.py for file size compliance.
"""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    Idempotency,
    RequestId,
    require_mission_access,
)
from modules.backend.core.exceptions import AuthorizationError, NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.workflow import WorkflowEdgeSchema
from modules.backend.schemas.workflow_schedule import (
    WorkflowScheduleCreateRequest,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdateRequest,
)

router = APIRouter()


# ---- Mission-scoped workflows ----


@router.get(
    "/{mission_id}/workflows",
    response_model=ApiResponse,
    summary="List mission workflows",
)
async def list_mission_workflows(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List DB-stored workflow definitions for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflows = await service.list_workflows(mission_id, enabled_only=enabled_only)
    items = [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "version": w.version,
            "enabled": w.enabled,
            "trigger_type": w.trigger_type,
            "step_count": w.step_count,
            "designed_by": w.designed_by,
            "locked_at": w.locked_at,
            "edges_json": w.edges_json,
        }
        for w in workflows
    ]
    return ApiResponse(
        success=True,
        data={"workflows": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/workflow-runs",
    response_model=ApiResponse,
    summary="List workflow runs for a mission",
)
async def list_workflow_runs(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    workflow_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """List past and in-flight workflow runs for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_run import WorkflowRunService

    service = WorkflowRunService(db)
    runs, total = await service.list_runs(
        mission_id=mission_id,
        workflow_name=workflow_name,
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [
        {
            "id": r.id,
            "workflow_name": r.workflow_name,
            "workflow_version": r.workflow_version,
            "status": r.status.name if hasattr(r.status, "name") else str(r.status),
            "trigger_type": r.trigger_type,
            "triggered_by": r.triggered_by,
            "total_cost_usd": float(r.total_cost_usd or 0),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_data": r.error_data,
            "result_summary": r.result_summary,
        }
        for r in runs
    ]
    return ApiResponse(
        success=True,
        data={"runs": items, "total": total},
        metadata={"request_id": request_id},
    )


class CreateWorkflowRequest(BaseModel):
    """Request body for creating a new blank workflow."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(default="", max_length=500)


@router.post(
    "/{mission_id}/workflows",
    response_model=ApiResponse,
    summary="Create a new blank workflow",
)
async def create_workflow(
    mission_id: str,
    data: CreateWorkflowRequest,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Create a new blank workflow definition for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflow = await service.create_workflow(
        mission_id=mission_id,
        name=data.name,
        description=data.description,
        objective={
            "statement": data.description or data.name,
            "category": "general",
            "owner": "user",
            "priority": "medium",
        },
        steps=[],
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "mission_id": workflow.mission_id,
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflows/import",
    response_model=ApiResponse,
    summary="Import workflow from template",
)
async def import_workflow_template(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    template_name: str = "",
    name_override: str | None = None,
) -> ApiResponse:
    """Import a YAML workflow template as a DB-stored workflow for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflow = await service.import_from_template(
        mission_id=mission_id,
        template_name=template_name,
        name_override=name_override,
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "mission_id": workflow.mission_id,
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/workflows/{workflow_name}",
    response_model=ApiResponse,
    summary="Get mission workflow detail",
)
async def get_mission_workflow(
    mission_id: str,
    workflow_name: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get a mission workflow with full step definitions."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    w = await service.get_workflow(mission_id, workflow_name)
    return ApiResponse(
        success=True,
        data={
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "version": w.version,
            "enabled": w.enabled,
            "trigger_type": w.trigger_type,
            "step_count": w.step_count,
            "designed_by": w.designed_by,
            "locked_at": w.locked_at,
            "steps": w.steps,
            "edges_json": w.edges_json,
            "canvas_state": w.canvas_state,
            "objective": w.objective,
            "budget_config": w.budget_config,
            "trigger_config": w.trigger_config,
            "parameters": w.parameters,
            "context": w.context,
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflows/{workflow_name}/run",
    response_model=ApiResponse,
    summary="Run a workflow by name",
)
async def run_mission_workflow(
    mission_id: str,
    workflow_name: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    idempotency: Idempotency,
    body: dict | None = None,
) -> ApiResponse:
    """Run a workflow by name against a mission.

    Resolves the workflow from mission-scoped definitions first,
    then falls back to system templates.

    Optional body fields:
        triggered_by: str — trigger origin (default: "user:api")
        gate_mode: str — gate override (off, interactive, etc.)
        context_overrides: dict — merge into workflow context before execution

    Supports Idempotency-Key header — safe to retry on network timeout.
    """
    await require_mission_access(db, mission_id, current_user)

    # Return cached response if this run was already started
    if idempotency:
        cached = await idempotency.get_cached_response()
        if cached:
            return ApiResponse(**cached)

    from fastapi import HTTPException
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.workflow_run import WorkflowRunService

    body = body or {}
    triggered_by = body.get("triggered_by", "user:api")
    context_overrides = body.get("context_overrides")
    gate_mode_override = body.get("gate_mode")

    # Resolve effective gate mode: explicit body override wins, else fall
    # back to the plan's persisted gate_mode. Interactive modes return
    # the endpoint immediately (Plan 80h) — synchronous blocking is
    # meaningless when the workflow is waiting on operator approval.
    from modules.backend.services.mission_plan import MissionPlanService

    existing_plan = await MissionPlanService(db).get_plan(mission_id)
    effective_gate_mode = gate_mode_override or (existing_plan.gate_mode if existing_plan else None)
    interactive = effective_gate_mode in ("manual", "interactive", "ai_assisted")

    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis, mission_id=mission_id)

    if interactive:
        # The workflow proceeds durably in Temporal — no chat session to
        # notify, no in-process background task that would die with the
        # backend process on a crash or restart (Plan 84 Phase 3.1).
        await redis.aclose()

        from modules.backend.temporal.client import get_temporal_client, get_temporal_config
        from modules.backend.temporal.tool_fork_models import RunWorkflowInput
        from modules.backend.temporal.tool_fork_workflow import RunWorkflowWorkflow

        try:
            client = await get_temporal_client()
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Temporal required for workflow execution: {e}",
            )
        config = get_temporal_config()

        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            record = await svc.create_background_record(
                mission_id=mission_id,
                session_id=None,
                task_type="run_workflow",
                objective=f"Run workflow: {workflow_name}",
                params={"workflow_name": workflow_name, "context_overrides": context_overrides},
            )
            record_id = record.id

        # Deterministic ID (no random suffix) so a retried request with the
        # same Idempotency-Key (Phase 3.2) dedupes against the same
        # Temporal execution instead of starting a second run.
        workflow_id = f"workflow-run-{record_id}"
        await client.start_workflow(
            RunWorkflowWorkflow.run,
            RunWorkflowInput(
                mission_id=mission_id,
                session_id=None,
                execution_record_id=record_id,
                workflow_name=workflow_name,
                context_overrides=context_overrides,
                triggered_by=triggered_by,
            ),
            id=workflow_id,
            task_queue=config.task_queue,
        )

        async with ExecutionPersistenceService.factory() as svc:
            existing = await svc.get_execution(record_id)
            if existing is not None:
                existing.temporal_workflow_id = workflow_id

        response = ApiResponse(
            success=True,
            data={
                "status": "pending_approval",
                "workflow_name": workflow_name,
                "gate_mode": effective_gate_mode,
                "execution_record_id": record_id,
                "temporal_workflow_id": workflow_id,
                "next": "Approve tasks via `mc plan approve <task_id>` or "
                "`mc plan approve --next`. View pending tasks with "
                "`mc plan show --status proposed`.",
            },
            metadata={"request_id": request_id},
        )
        if idempotency:
            await idempotency.cache_response(response.model_dump())
        return response

    # Autonomous mode: synchronous (legacy behaviour).
    try:
        async with WorkflowRunService.factory(event_bus=event_bus) as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by=triggered_by,
                mission_id=mission_id,
                context_overrides=context_overrides,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        await redis.aclose()

    response = ApiResponse(
        success=True,
        data={
            "run_id": run.id,
            "workflow_name": run.workflow_name,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "total_cost_usd": run.total_cost_usd,
        },
        metadata={"request_id": request_id},
    )
    if idempotency:
        await idempotency.cache_response(response.model_dump())
    return response


@router.delete(
    "/{mission_id}/workflows/{workflow_id}",
    response_model=ApiResponse,
    summary="Delete a workflow definition",
)
async def delete_mission_workflow(
    mission_id: str,
    workflow_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Delete a workflow definition. Requires admin role."""
    if not current_user.has_role("admin"):
        raise AuthorizationError("Deleting workflows requires admin role")

    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    await service.delete_workflow(workflow_id)
    return ApiResponse(
        success=True,
        data={"deleted": workflow_id},
        metadata={"request_id": request_id},
    )


# ---- Workflow graph (visual editor) ----


class SaveGraphRequest(BaseModel):
    """Request body for saving workflow canvas state, edges, and optionally steps."""

    canvas_state: dict[str, Any] = Field(default_factory=dict)
    edges_json: list[WorkflowEdgeSchema] | None = None
    steps: list[dict[str, Any]] | None = None


@router.put(
    "/{mission_id}/workflows/{workflow_id}/graph",
    response_model=ApiResponse,
    summary="Save workflow graph canvas state",
)
async def save_workflow_graph(
    mission_id: str,
    workflow_id: str,
    data: SaveGraphRequest,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Save canvas viewport, node positions, and optionally edges for the visual editor."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    edges_payload = (
        [e.model_dump() for e in data.edges_json] if data.edges_json is not None else None
    )
    workflow, warnings = await service.save_graph(
        workflow_id=workflow_id,
        canvas_state=data.canvas_state,
        edges_json=edges_payload,
        steps=data.steps,
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "version": workflow.version,
            "canvas_state": workflow.canvas_state,
            "edges_json": workflow.edges_json,
            "steps": workflow.steps,
            "validation_warnings": warnings,
        },
        metadata={"request_id": request_id},
    )


class ValidateGraphRequest(BaseModel):
    """Request body for validating a workflow graph."""

    steps: list[dict[str, Any]]
    edges_json: list[WorkflowEdgeSchema] = Field(default_factory=list)


@router.post(
    "/{mission_id}/workflows/{workflow_id}/validate",
    response_model=ApiResponse,
    summary="Validate workflow graph",
)
async def validate_workflow_graph_endpoint(
    mission_id: str,
    workflow_id: str,
    data: ValidateGraphRequest,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Validate a workflow graph without saving. Returns validation errors/warnings."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_validator import validate_workflow_graph

    errors = validate_workflow_graph(
        data.steps,
        [e.model_dump() for e in data.edges_json],
        current_workflow_id=workflow_id,
    )
    return ApiResponse(
        success=len(errors) == 0,
        data={
            "valid": len(errors) == 0,
            "errors": errors,
            "step_count": len(data.steps),
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/workflow-runs/{run_id}",
    response_model=ApiResponse,
    summary="Get single workflow run detail",
)
async def get_workflow_run(
    mission_id: str,
    run_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get a single workflow run by ID."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_run import WorkflowRunService

    run = await WorkflowRunService(db).get_run(run_id)
    if run is None or run.mission_id != mission_id:
        raise NotFoundError(f"Workflow run {run_id} not found in mission {mission_id}")

    return ApiResponse(
        success=True,
        data={
            "id": run.id,
            "workflow_name": run.workflow_name,
            "workflow_version": run.workflow_version,
            "status": run.status.name if hasattr(run.status, "name") else str(run.status),
            "trigger_type": run.trigger_type,
            "triggered_by": run.triggered_by,
            "total_cost_usd": float(run.total_cost_usd or 0),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_data": run.error_data,
            "result_summary": run.result_summary,
            "context": run.context,
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflow-runs/{run_id}/cancel",
    response_model=ApiResponse,
    summary="Cancel a workflow run",
)
async def cancel_workflow_run(
    mission_id: str,
    run_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Mark a workflow run as CANCELLED.

    Use cases:
      - Stale RUNNING rows whose dispatcher coroutine died on backend
        restart (Plan 80h orphan recovery).
      - Operator-aborted runs.

    Idempotent: no-op when the run is already in a terminal state.
    """
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_run import WorkflowRunService

    service = WorkflowRunService(db)
    run, changed = await service.cancel_run(run_id, mission_id=mission_id)
    if not changed:
        current = run.status.value if hasattr(run.status, "value") else str(run.status)
        return ApiResponse(
            success=True,
            data={
                "id": run.id,
                "status": str(current),
                "message": "Already in terminal state — no-op.",
            },
            metadata={"request_id": request_id},
        )

    run_id_value = run.id
    await db.commit()

    return ApiResponse(
        success=True,
        data={"id": run_id_value, "status": "CANCELLED"},
        metadata={"request_id": request_id},
    )


# ---- Workflow schedules ----


@router.get(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="List mission schedules",
)
async def list_mission_schedules(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List workflow schedules for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedules = await service.list_by_mission(mission_id, enabled_only=enabled_only)
    items = [WorkflowScheduleResponse.model_validate(s).model_dump() for s in schedules]
    return ApiResponse(
        success=True,
        data={"schedules": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="Create workflow schedule",
)
async def create_mission_schedule(
    mission_id: str,
    data: WorkflowScheduleCreateRequest,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Create a cron-based schedule for a workflow."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedule = await service.create_schedule(
        workflow_definition_id=data.workflow_definition_id,
        mission_id=mission_id,
        cron_expression=data.cron_expression,
        timezone=data.timezone,
        description=data.description,
        budget_per_run_usd=data.budget_per_run_usd,
        max_iterations=data.max_iterations,
        cooldown_seconds=data.cooldown_seconds,
        created_by="user:api",
    )
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Update workflow schedule",
)
async def update_mission_schedule(
    mission_id: str,
    schedule_id: str,
    data: WorkflowScheduleUpdateRequest,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Update a workflow schedule's configuration."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    updates = data.model_dump(exclude_none=True)
    schedule = await service.update_schedule(schedule_id, **updates)
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Delete workflow schedule",
)
async def delete_mission_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Delete a workflow schedule."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    await service.delete_schedule(schedule_id)
    return ApiResponse(
        success=True,
        data={"deleted": schedule_id},
        metadata={"request_id": request_id},
    )


# ---- Workflow Architect ----


@router.post(
    "/{mission_id}/architect/chat",
    response_model=ApiResponse,
    summary="Chat with the Workflow Architect",
)
async def architect_chat(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    message: str = Query(..., min_length=1, description="Message for the Workflow Architect"),
    session_id: str | None = None,
) -> ApiResponse:
    """Send a message to the Workflow Architect for conversational design.

    The architect browses the agent catalog, proposes workflows,
    validates them, and saves confirmed designs.
    """
    await require_mission_access(db, mission_id, current_user)
    from pydantic_ai.exceptions import ModelHTTPError

    # Capture graph events emitted by the render_graph tool, plus every
    # AgentToolCall/Result event so the client can verify which tools
    # actually ran (catches model confabulation about phantom tool errors).
    from modules.backend.events.types import (
        AgentToolCallEvent,
        AgentToolResultEvent,
        WorkflowGraphEvent,
    )
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    captured_graphs: list[dict] = []
    tool_trace: list[dict] = []

    async def capture_event(event):
        if isinstance(event, WorkflowGraphEvent):
            captured_graphs.append(event.graph_data)
        elif isinstance(event, AgentToolCallEvent):
            tool_trace.append(
                {
                    "phase": "call",
                    "tool": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "args": event.tool_args,
                }
            )
        elif isinstance(event, AgentToolResultEvent):
            tool_trace.append(
                {
                    "phase": "result",
                    "tool": event.tool_name,
                    "tool_call_id": event.tool_call_id,
                    "status": event.status,
                    "result": event.result,
                    "error_detail": event.error_detail,
                }
            )

    # Synthesise an ephemeral session id for stateless calls so tool events
    # can carry a valid UUID. Real session_id wins when the client passes one.
    import uuid as _uuid

    effective_session_id = session_id or str(_uuid.uuid4())

    service = WorkflowArchitectService(db)
    try:
        result = await service.chat(
            mission_id=mission_id,
            message=message,
            session_id=effective_session_id,
            on_event=capture_event,
        )
    except ModelHTTPError as e:
        body = e.body if isinstance(e.body, dict) else {}
        error_detail = body.get("error", {})
        api_message = (
            error_detail.get("message", str(e)) if isinstance(error_detail, dict) else str(e)
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=502,
            content=ApiResponse(
                success=False,
                data=None,
                error={"code": "MODEL_ERROR", "message": api_message},
                metadata={"request_id": request_id},
            ).model_dump(),
        )

    data: dict = {
        "response": result.get("response", ""),
        "usage": str(result.get("usage")) if result.get("usage") else None,
        "tool_trace": tool_trace,
    }
    if captured_graphs:
        data["graph_proposal"] = captured_graphs[-1]  # last rendered graph

    return ApiResponse(
        success=True,
        data=data,
        metadata={"request_id": request_id},
    )


# ---- Human Input ----


class HumanInputSubmission(BaseModel):
    """Request body for responding to a human input request."""

    response: str = Field(..., min_length=1, max_length=5000)
    responder_id: str = ""


@router.get(
    "/{mission_id}/human-input/pending",
    response_model=ApiResponse,
    summary="List pending human input requests",
)
async def list_pending_human_input(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """List pending human input requests for a mission."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.workflow_run import WorkflowRunService

    requests = await WorkflowRunService(db).list_pending_human_input(mission_id)
    items = [
        {
            "id": r.id,
            "workflow_run_id": r.workflow_run_id,
            "step_id": r.step_id,
            "prompt_message": r.prompt_message,
            "channel": r.channel,
            "choices": r.choices_json,
            "timeout_at": r.timeout_at.isoformat() if r.timeout_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in requests
    ]
    return ApiResponse(
        success=True,
        data={"requests": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/human-input/{input_request_id}/respond",
    response_model=ApiResponse,
    summary="Respond to a human input request",
)
async def respond_to_human_input(
    mission_id: str,
    input_request_id: str,
    data: HumanInputSubmission,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Submit a response to a pending human input request.

    Sends a Temporal Signal to the HumanInputWorkflow.
    """
    from fastapi import HTTPException

    from modules.backend.services.workflow_run import WorkflowRunService

    await require_mission_access(db, mission_id, current_user)

    # Mission scoping + pending check live in the service — it raises
    # NotFoundError (404) / ConflictError (409) accordingly.
    req = await WorkflowRunService(db).get_pending_human_input_request(mission_id, input_request_id)

    # Validate response against choices if constrained
    if req.choices_json and data.response not in req.choices_json:
        raise HTTPException(
            status_code=422,
            detail=f"Response must be one of: {', '.join(req.choices_json)}",
        )

    # Send Temporal Signal
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.human_input_models import HumanInputResponse
    from modules.backend.temporal.human_input_workflow import HumanInputWorkflow

    client = await get_temporal_client()
    handle = client.get_workflow_handle(req.temporal_workflow_id)
    await handle.signal(
        HumanInputWorkflow.submit_human_input,
        HumanInputResponse(
            response=data.response,
            # Identity comes from the authenticated user, not the body.
            responder_id=str(current_user.id),
        ),
    )

    return ApiResponse(
        success=True,
        data={"request_id": input_request_id, "status": "signal_sent"},
        metadata={"request_id": request_id},
    )
