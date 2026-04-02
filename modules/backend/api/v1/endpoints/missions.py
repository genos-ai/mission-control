"""
Mission management API endpoints.

CRUD for missions, team management, and mission-scoped workflow listing.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import (
    MissionCreate,
    MissionMemberAddRequest,
    MissionMemberResponse,
    MissionMemberUpdateRequest,
    MissionResponse,
    MissionUpdate,
)
from modules.backend.schemas.mission_team import (
    AgentConfigSummary,
    MissionTeamAddRequest,
    MissionTeamMemberResponse,
    UserPromptUpdateRequest,
)
from modules.backend.schemas.workflow_schedule import (
    WorkflowScheduleCreateRequest,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdateRequest,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_team import MissionTeamService

router = APIRouter()


# ---- Mission CRUD ----


@router.post("", response_model=ApiResponse, summary="Create mission")
async def create_mission(
    data: MissionCreate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a new mission.

    Platform missions (tier='platform') require admin role.
    """
    # TODO: enforce admin role for platform missions when auth middleware is wired
    # if data.tier == "platform" and current_user.role != "admin":
    #     raise HTTPException(403, "Platform missions require admin role")

    service = MissionService(db)
    mission = await service.create_mission(
        name=data.name,
        description=data.description,
        brief=data.brief,
        owner_id=data.owner_id,
        team_id=data.team_id,
        default_roster=data.default_roster,
        budget_ceiling_usd=data.budget_ceiling_usd,
        repo_url=data.repo_url,
        repo_root=data.repo_root,
        tier=data.tier,
    )
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get("", response_model=ApiResponse, summary="List missions")
async def list_missions(
    db: DbSession,
    request_id: RequestId,
    owner_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ApiResponse:
    """List missions with optional filters."""
    service = MissionService(db)
    missions = await service.list_missions(
        owner_id=owner_id, status=status, limit=limit,
    )
    items = [MissionResponse.model_validate(m).model_dump() for m in missions]
    return ApiResponse(
        success=True,
        data={"missions": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get("/{mission_id}", response_model=ApiResponse, summary="Get mission detail")
async def get_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get mission detail by ID."""
    service = MissionService(db)
    mission = await service.get_mission(mission_id)
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/environment",
    response_model=ApiResponse,
    summary="Get execution environment status",
)
async def get_mission_environment(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get the execution environment (container/worktree) status for a mission."""
    from sqlalchemy import select
    from modules.backend.models.execution_environment import ExecutionEnvironmentModel

    result = await db.execute(
        select(ExecutionEnvironmentModel).where(
            ExecutionEnvironmentModel.mission_id == mission_id,
        ).order_by(ExecutionEnvironmentModel.created_at.desc())
    )
    envs = list(result.scalars().all())

    environments = []
    for env in envs:
        environments.append({
            "id": str(env.id),
            "mode": env.mode,
            "status": env.status,
            "container_name": env.container_name,
            "image": env.image,
            "execution_count": env.execution_count,
            "last_execution_at": env.last_execution_at,
            "created_at": str(env.created_at),
        })

    # Find the active one
    active = next((e for e in environments if e["status"].lower() == "running"), None)

    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "active_environment": active,
            "all_environments": environments,
        },
        metadata={"request_id": request_id},
    )


@router.patch("/{mission_id}", response_model=ApiResponse, summary="Update mission")
async def update_mission(
    mission_id: str,
    data: MissionUpdate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update mission fields."""
    service = MissionService(db)
    updates = data.model_dump(exclude_none=True)
    mission = await service.update_mission(mission_id, **updates)
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ---- Team management ----


@router.get(
    "/{mission_id}/team",
    response_model=ApiResponse,
    summary="List mission team",
)
async def list_mission_team(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List agents on a mission's team with catalog configuration."""
    service = MissionTeamService(db)
    members = await service.list_team(mission_id, enabled_only=enabled_only)
    items = []
    for m in members:
        resp = MissionTeamMemberResponse.model_validate(m)
        if m.agent_catalog:
            resp.agent = AgentConfigSummary(
                agent_name=m.agent_catalog.agent_name,
                agent_type=m.agent_catalog.agent_type,
                description=m.agent_catalog.description,
                model=m.agent_catalog.model_config_json,
                tools=m.agent_catalog.tools,
                scope=m.agent_catalog.scope,
                constraints=m.agent_catalog.constraints,
            )
        items.append(resp.model_dump())
    return ApiResponse(
        success=True,
        data={"team_members": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/team",
    response_model=ApiResponse,
    summary="Add agent to team",
)
async def add_agent_to_team(
    mission_id: str,
    data: MissionTeamAddRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Add an agent from the catalog to a mission's team."""
    service = MissionTeamService(db)
    member = await service.add_agent(
        mission_id=mission_id,
        agent_catalog_id=data.agent_catalog_id,
        user_prompt=data.user_prompt,
        display_order=data.display_order,
        custom_constraints=data.custom_constraints,
    )
    response = MissionTeamMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/team/seed",
    response_model=ApiResponse,
    summary="Seed team from catalog",
)
async def seed_team_from_catalog(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Populate mission team from all enabled catalog agents.

    Adds any catalog agents not already on the team. Idempotent.
    """
    service = MissionTeamService(db)
    added = await service.seed_from_catalog(mission_id)
    await db.commit()
    items = [
        MissionTeamMemberResponse.model_validate(m).model_dump()
        for m in added
    ]
    return ApiResponse(
        success=True,
        data={"added": items, "added_count": len(items)},
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/team/{member_id}",
    response_model=ApiResponse,
    summary="Remove agent from team",
)
async def remove_agent_from_team(
    mission_id: str,
    member_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Remove an agent from a mission's team."""
    service = MissionTeamService(db)
    await service.remove_agent(member_id)
    return ApiResponse(
        success=True,
        data={"removed": member_id},
        metadata={"request_id": request_id},
    )


@router.put(
    "/{mission_id}/team/{member_id}/prompt",
    response_model=ApiResponse,
    summary="Update user prompt",
)
async def update_team_member_prompt(
    mission_id: str,
    member_id: str,
    data: UserPromptUpdateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a team member's user prompt with version tracking."""
    service = MissionTeamService(db)
    member = await service.update_user_prompt(
        member_id=member_id,
        content=data.content,
        changed_by=data.changed_by,
        change_reason=data.change_reason,
    )
    response = MissionTeamMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/team/{member_id}/prompt-history",
    response_model=ApiResponse,
    summary="Get user prompt version history",
)
async def get_team_member_prompt_history(
    mission_id: str,
    member_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get the user prompt version history for a team member."""
    service = MissionTeamService(db)
    versions = await service.get_prompt_history(member_id)
    items = [
        {
            "version": v.version,
            "content": v.content,
            "changed_by": v.changed_by,
            "change_reason": v.change_reason,
            "created_at": str(v.created_at),
        }
        for v in versions
    ]
    return ApiResponse(
        success=True,
        data={"member_id": member_id, "versions": items},
        metadata={"request_id": request_id},
    )


# ---- Mission membership (human users) ----


@router.get(
    "/{mission_id}/members",
    response_model=ApiResponse,
    summary="List mission members",
)
async def list_mission_members(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """List human members of a mission."""
    service = MissionService(db)
    members = await service.list_members(mission_id)
    items = [
        MissionMemberResponse.model_validate(m).model_dump()
        for m in members
    ]
    return ApiResponse(
        success=True,
        data={"members": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/members",
    response_model=ApiResponse,
    summary="Add user to mission",
)
async def add_mission_member(
    mission_id: str,
    data: MissionMemberAddRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Add a human user to a mission with a specified role."""
    service = MissionService(db)
    member = await service.add_member(
        mission_id=mission_id,
        user_id=data.user_id,
        role=data.role,
    )
    response = MissionMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/members/{user_id}",
    response_model=ApiResponse,
    summary="Update member role",
)
async def update_mission_member(
    mission_id: str,
    user_id: str,
    data: MissionMemberUpdateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a mission member's role."""
    service = MissionService(db)
    member = await service.update_member_role(
        mission_id=mission_id,
        user_id=user_id,
        role=data.role,
    )
    response = MissionMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/members/{user_id}",
    response_model=ApiResponse,
    summary="Remove user from mission",
)
async def remove_mission_member(
    mission_id: str,
    user_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Remove a human user from a mission."""
    service = MissionService(db)
    await service.remove_member(mission_id=mission_id, user_id=user_id)
    return ApiResponse(
        success=True,
        data={"removed": user_id, "mission_id": mission_id},
        metadata={"request_id": request_id},
    )


# ---- Mission-scoped workflows ----


@router.get(
    "/{mission_id}/workflows",
    response_model=ApiResponse,
    summary="List mission workflows",
)
async def list_mission_workflows(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List DB-stored workflow definitions for a mission."""
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
        }
        for w in workflows
    ]
    return ApiResponse(
        success=True,
        data={"workflows": items, "total": len(items)},
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
    request_id: RequestId,
    template_name: str = "",
    name_override: str | None = None,
) -> ApiResponse:
    """Import a YAML workflow template as a DB-stored workflow for a mission."""
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
    request_id: RequestId,
) -> ApiResponse:
    """Get a mission workflow with full step definitions."""
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
            "objective": w.objective,
            "budget_config": w.budget_config,
            "trigger_config": w.trigger_config,
            "context": w.context,
        },
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
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List workflow schedules for a mission."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedules = await service.list_by_mission(mission_id, enabled_only=enabled_only)
    items = [
        WorkflowScheduleResponse.model_validate(s).model_dump()
        for s in schedules
    ]
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
    request_id: RequestId,
) -> ApiResponse:
    """Create a cron-based schedule for a workflow."""
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
    request_id: RequestId,
) -> ApiResponse:
    """Update a workflow schedule's configuration."""
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
    request_id: RequestId,
) -> ApiResponse:
    """Delete a workflow schedule."""
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
    request_id: RequestId,
    message: str = Query(..., min_length=1, description="Message for the Workflow Architect"),
    session_id: str | None = None,
) -> ApiResponse:
    """Send a message to the Workflow Architect for conversational design.

    The architect browses the agent catalog, proposes workflows,
    validates them, and saves confirmed designs.
    """
    from pydantic_ai.exceptions import ModelHTTPError
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    service = WorkflowArchitectService(db)
    try:
        result = await service.chat(
            mission_id=mission_id,
            message=message,
            session_id=session_id,
        )
    except ModelHTTPError as e:
        body = e.body if isinstance(e.body, dict) else {}
        error_detail = body.get("error", {})
        api_message = error_detail.get("message", str(e)) if isinstance(error_detail, dict) else str(e)
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

    return ApiResponse(
        success=True,
        data={
            "response": result.get("response", ""),
            "usage": str(result.get("usage")) if result.get("usage") else None,
        },
        metadata={"request_id": request_id},
    )


# ---- Mission Context (MCD) ----


@router.get(
    "/{mission_id}/context",
    response_model=ApiResponse,
    summary="Get Mission Context Document",
)
async def get_mission_context(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get the full MCD content with version and size metrics."""
    from modules.backend.services.mission_context import MissionContextManager

    manager = MissionContextManager(db)
    context_data = await manager.get_context(mission_id)
    size = await manager.get_context_size(mission_id)
    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "context_data": context_data,
            **size,
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/context/history",
    response_model=ApiResponse,
    summary="Get MCD change history",
)
async def get_context_history(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    limit: int = Query(30, ge=1, le=100),
) -> ApiResponse:
    """Get recent changes to the Mission Context Document."""
    from modules.backend.schemas.mission_context import ContextChangeResponse
    from modules.backend.services.mission_context import MissionContextManager

    manager = MissionContextManager(db)
    changes = await manager.get_history(mission_id, limit=limit)
    items = [ContextChangeResponse.model_validate(c).model_dump() for c in changes]
    return ApiResponse(
        success=True,
        data={"changes": items, "total": len(items)},
        metadata={"request_id": request_id},
    )
