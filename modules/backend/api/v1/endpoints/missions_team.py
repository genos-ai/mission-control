"""
Mission team management API endpoints.

Agent team CRUD and human membership management for missions.
Split from missions.py for file size compliance.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_mission_access,
    require_mission_owner,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import (
    MissionMemberAddRequest,
    MissionMemberResponse,
    MissionMemberUpdateRequest,
)
from modules.backend.schemas.mission_team import (
    AgentConfigSummary,
    MissionTeamAddRequest,
    MissionTeamMemberResponse,
    UserPromptUpdateRequest,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_team import MissionTeamService

router = APIRouter()


# ---- Agent team management ----


@router.get(
    "/{mission_id}/team",
    response_model=ApiResponse,
    summary="List mission team",
)
async def list_mission_team(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List agents on a mission's team with catalog configuration."""
    await require_mission_access(db, mission_id, current_user)
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
                chat_enabled=m.agent_catalog.chat_enabled,
                engine=m.agent_catalog.engine,
                effort=m.agent_catalog.effort,
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Add an agent from the catalog to a mission's team."""
    await require_mission_access(db, mission_id, current_user)
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
    "/{mission_id}/team/ping",
    response_model=ApiResponse,
    summary="Ping every agent on a mission's team",
)
async def ping_mission_team(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Send a trivial probe to every agent on the team to verify it's live.

    For each agent: build the model from its catalog row, send "Reply with OK",
    measure latency + tokens + cost. Skips system prompts and tools — this
    exercises the model + provider + auth chain, not the full agent machinery.
    """
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.agents.preflight import ping_agents

    service = MissionTeamService(db)
    members = await service.list_team(mission_id, enabled_only=True)
    agent_names = [m.agent_catalog.agent_name for m in members if m.agent_catalog is not None]
    results = await ping_agents(agent_names)
    payload = [
        {
            "agent_name": r.agent_name,
            "model_name": r.model_name,
            "ok": r.ok,
            "elapsed_ms": round(r.elapsed_ms, 1),
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd,
            "error": r.error,
        }
        for r in results
    ]
    return ApiResponse(
        success=True,
        data={
            "pings": payload,
            "total": len(payload),
            "failures": sum(1 for r in results if not r.ok),
        },
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Populate mission team from all enabled catalog agents.

    Adds any catalog agents not already on the team. Idempotent.
    """
    await require_mission_access(db, mission_id, current_user)
    service = MissionTeamService(db)
    added = await service.seed_from_catalog(mission_id)
    await db.commit()
    items = [MissionTeamMemberResponse.model_validate(m).model_dump() for m in added]
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Remove an agent from a mission's team."""
    await require_mission_access(db, mission_id, current_user)
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Update a team member's user prompt with version tracking."""
    await require_mission_access(db, mission_id, current_user)
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


@router.patch(
    "/{mission_id}/team/{member_id}/constraints",
    response_model=ApiResponse,
    summary="Update agent constraints",
)
async def update_team_member_constraints(
    mission_id: str,
    member_id: str,
    data: dict,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Update a team member's custom_constraints JSON.

    Merges the provided dict into the existing constraints (or replaces
    if the existing value is None). Used by the Team tab to configure
    per-agent settings like research_depth, include_domains, etc.
    """
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.repositories.mission_team import MissionTeamRepository

    repo = MissionTeamRepository(db)
    member = await repo.get_by_id(member_id)
    existing = member.custom_constraints or {}
    member.custom_constraints = {**existing, **data}
    await db.flush()
    await db.refresh(member)
    await db.commit()

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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get the user prompt version history for a team member."""
    await require_mission_access(db, mission_id, current_user)
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


# ---- Human membership ----


@router.get(
    "/{mission_id}/members",
    response_model=ApiResponse,
    summary="List mission members",
)
async def list_mission_members(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """List human members of a mission."""
    await require_mission_access(db, mission_id, current_user)
    service = MissionService(db)
    members = await service.list_members(mission_id)
    items = [MissionMemberResponse.model_validate(m).model_dump() for m in members]
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Add a human user to a mission with a specified role."""
    await require_mission_owner(db, mission_id, current_user)
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Update a mission member's role."""
    await require_mission_owner(db, mission_id, current_user)
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
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Remove a human user from a mission."""
    await require_mission_owner(db, mission_id, current_user)
    service = MissionService(db)
    await service.remove_member(mission_id=mission_id, user_id=user_id)
    return ApiResponse(
        success=True,
        data={"removed": user_id, "mission_id": mission_id},
        metadata={"request_id": request_id},
    )
