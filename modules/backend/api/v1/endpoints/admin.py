"""
Admin API Endpoints.

Protected by admin role (X-API-Key header). Provides:
- Agent catalog CRUD with system prompt editor
- Platform metrics and cost analytics
- System operations (health, seed catalog, config view)
- User/role management
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modules.backend.core.dependencies import AdminRole, DbSession, RequestId
from modules.backend.schemas.base import ApiResponse

router = APIRouter()


# ---- Schemas ----


class CatalogCreateRequest(BaseModel):
    agent_name: str
    agent_type: str
    description: str
    system_prompt: str = ""
    version: str = "1.0.0"
    tools: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
    visibility: str = "public"
    model_config_json: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    interface: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None


class CatalogUpdateRequest(BaseModel):
    description: str | None = None
    enabled: bool | None = None
    visibility: str | None = None
    version: str | None = None
    tools: list[str] | None = None
    keywords: list[str] | None = None
    model_config_json: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    interface: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None


class SystemPromptUpdateRequest(BaseModel):
    content: str
    change_reason: str | None = None


class RoleAssignRequest(BaseModel):
    user_id: str
    role: str


# ---- Catalog CRUD ----


@router.get(
    "/catalog",
    response_model=ApiResponse,
    summary="List all agents (including disabled)",
)
async def admin_catalog_list(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    enabled_only: bool = False,
) -> ApiResponse:
    """List all agent catalog entries, including disabled ones."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    entries = await service.list_catalog(enabled_only=enabled_only)

    return ApiResponse(
        success=True,
        data={
            "agents": [
                {
                    "id": e.id,
                    "agent_name": e.agent_name,
                    "agent_type": e.agent_type,
                    "version": e.version,
                    "description": e.description,
                    "enabled": e.enabled,
                    "visibility": e.visibility,
                    "tools": e.tools,
                    "keywords": e.keywords,
                }
                for e in entries
            ],
            "count": len(entries),
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/catalog",
    response_model=ApiResponse,
    summary="Create agent catalog entry",
)
async def admin_catalog_create(
    body: CatalogCreateRequest,
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Create a new agent in the catalog."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    entry = await service.create_entry(
        agent_name=body.agent_name,
        agent_type=body.agent_type,
        description=body.description,
        system_prompt=body.system_prompt,
        version=body.version,
        tools=body.tools,
        keywords=body.keywords,
        enabled=body.enabled,
        visibility=body.visibility,
        model_config_json=body.model_config_json,
        scope=body.scope,
        interface=body.interface,
        constraints=body.constraints,
    )

    return ApiResponse(
        success=True,
        data={"id": entry.id, "agent_name": entry.agent_name},
        metadata={"request_id": request_id},
    )


@router.patch(
    "/catalog/{agent_name}",
    response_model=ApiResponse,
    summary="Update agent catalog entry",
)
async def admin_catalog_update(
    agent_name: str,
    body: CatalogUpdateRequest,
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Update fields on an existing agent catalog entry."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if not updates:
        return ApiResponse(
            success=False,
            data={"error": "No fields to update"},
            metadata={"request_id": request_id},
        )

    entry = await service.update_entry(agent_name, **updates)

    return ApiResponse(
        success=True,
        data={"id": entry.id, "agent_name": entry.agent_name, "updated_fields": list(updates.keys())},
        metadata={"request_id": request_id},
    )


@router.delete(
    "/catalog/{agent_name}",
    response_model=ApiResponse,
    summary="Delete agent catalog entry",
)
async def admin_catalog_delete(
    agent_name: str,
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Delete an agent from the catalog."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    entry = await service.get_by_name(agent_name)
    await db.delete(entry)
    await db.flush()

    return ApiResponse(
        success=True,
        data={"deleted": agent_name},
        metadata={"request_id": request_id},
    )


@router.put(
    "/catalog/{agent_name}/prompt",
    response_model=ApiResponse,
    summary="Update agent system prompt",
)
async def admin_catalog_update_prompt(
    agent_name: str,
    body: SystemPromptUpdateRequest,
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Update an agent's system prompt with version tracking."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    entry = await service.update_system_prompt(
        agent_name=agent_name,
        content=body.content,
        changed_by="admin:api",
        change_reason=body.change_reason,
    )

    return ApiResponse(
        success=True,
        data={
            "agent_name": entry.agent_name,
            "prompt_length": len(entry.system_prompt),
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/catalog/{agent_name}/prompt-history",
    response_model=ApiResponse,
    summary="Get agent prompt version history",
)
async def admin_catalog_prompt_history(
    agent_name: str,
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Get version history for an agent's system prompt."""
    from modules.backend.repositories.prompt_version import PromptVersionRepository
    from modules.backend.services.agent_catalog import AgentCatalogService

    catalog_svc = AgentCatalogService(db)
    entry = await catalog_svc.get_by_name(agent_name)

    pv_repo = PromptVersionRepository(db)
    versions = await pv_repo.list_versions(
        entity_type="agent_catalog",
        entity_id=entry.id,
    )

    return ApiResponse(
        success=True,
        data={
            "agent_name": agent_name,
            "versions": [
                {
                    "version": v.version,
                    "changed_by": v.changed_by,
                    "change_reason": v.change_reason,
                    "content_length": len(v.content),
                    "created_at": v.created_at,
                }
                for v in versions
            ],
        },
        metadata={"request_id": request_id},
    )


# ---- Seed Catalog ----


@router.post(
    "/seed-catalog",
    response_model=ApiResponse,
    summary="Seed agent catalog from YAML configs",
)
async def admin_seed_catalog(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    force: bool = False,
) -> ApiResponse:
    """Seed the agent catalog from config/agents/ YAML files."""
    from modules.backend.services.agent_catalog import AgentCatalogService
    from modules.backend.services.catalog_seeder import seed_catalog

    service = AgentCatalogService(db)
    result = await seed_catalog(service, force=force)

    return ApiResponse(
        success=True,
        data=result,
        metadata={"request_id": request_id},
    )


# ---- Platform Metrics ----


@router.get(
    "/metrics/overview",
    response_model=ApiResponse,
    summary="Platform overview metrics",
)
async def admin_metrics_overview(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Get high-level platform counts and total cost."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    service = PlatformMetricsService(db)
    overview = await service.get_overview()

    return ApiResponse(
        success=True,
        data=overview,
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/costs",
    response_model=ApiResponse,
    summary="Cost breakdown by agent and status",
)
async def admin_metrics_costs(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Get cost summary broken down by agent and execution status."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    service = PlatformMetricsService(db)
    costs = await service.get_cost_summary()

    return ApiResponse(
        success=True,
        data=costs,
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/agents",
    response_model=ApiResponse,
    summary="Agent utilisation stats",
)
async def admin_metrics_agents(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Get per-agent utilisation stats (runs, cost, duration)."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    service = PlatformMetricsService(db)
    utilisation = await service.get_agent_utilisation()

    return ApiResponse(
        success=True,
        data={"agents": utilisation},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/activity",
    response_model=ApiResponse,
    summary="Recent platform activity",
)
async def admin_metrics_activity(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    limit: int = 20,
) -> ApiResponse:
    """Get recent executions and workflow runs."""
    from modules.backend.services.platform_metrics import PlatformMetricsService

    service = PlatformMetricsService(db)
    activity = await service.get_recent_activity(limit=limit)

    return ApiResponse(
        success=True,
        data=activity,
        metadata={"request_id": request_id},
    )


# ---- System Operations ----


@router.get(
    "/config",
    response_model=ApiResponse,
    summary="View platform configuration",
)
async def admin_view_config(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """View current platform configuration (non-secret values only)."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()

    return ApiResponse(
        success=True,
        data={
            "application": {
                "name": config.application.name,
                "version": config.application.version,
                "environment": config.application.environment,
                "debug": config.application.debug,
            },
            "workflows": {
                "max_steps_per_workflow": config.workflows.max_steps_per_workflow,
                "default_budget_usd": config.workflows.default_budget_usd,
                "max_budget_usd": config.workflows.max_budget_usd,
                "max_concurrent_missions": config.workflows.max_concurrent_missions,
                "max_scheduled_runs_per_day": config.workflows.max_scheduled_runs_per_day,
                "schedule_evaluation_interval_seconds": config.workflows.schedule_evaluation_interval_seconds,
            },
            "sessions": {
                "default_ttl_hours": config.sessions.default_ttl_hours,
                "default_cost_budget_usd": config.sessions.default_cost_budget_usd,
                "max_cost_budget_usd": config.sessions.max_cost_budget_usd,
            },
            "notifications": {
                "enabled": config.notifications.enabled,
                "notify_on_completion": config.notifications.notify_on_completion,
                "notify_on_failure": config.notifications.notify_on_failure,
                "budget_warning_threshold_pct": config.notifications.budget_warning_threshold_pct,
            },
            "features": {
                "gateway_enabled": config.features.gateway_enabled,
                "agent_coordinator_enabled": config.features.agent_coordinator_enabled,
                "mcp_enabled": config.features.mcp_enabled,
                "events_publish_enabled": config.features.events_publish_enabled,
            },
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/system/health",
    response_model=ApiResponse,
    summary="Run system health check",
)
async def admin_health_check(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Run a comprehensive health check on all platform services."""
    from modules.backend.api.health import check_database, check_redis

    import asyncio

    db_check, redis_check = await asyncio.gather(
        check_database(),
        check_redis(),
        return_exceptions=True,
    )

    if isinstance(db_check, Exception):
        db_check = {"status": "error", "error": str(db_check)}
    if isinstance(redis_check, Exception):
        redis_check = {"status": "error", "error": str(redis_check)}

    checks = {"database": db_check, "redis": redis_check}
    all_healthy = all(
        c.get("status") in ("healthy", "not_configured")
        for c in checks.values()
    )

    return ApiResponse(
        success=True,
        data={
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
        },
        metadata={"request_id": request_id},
    )


# ---- User / Role Management ----


@router.get(
    "/roles",
    response_model=ApiResponse,
    summary="List configured roles",
)
async def admin_list_roles(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """List all configured roles and their levels."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()
    roles = {
        name: {"level": role.level, "description": role.description}
        for name, role in config.security.roles.items()
    }

    return ApiResponse(
        success=True,
        data={"roles": roles},
        metadata={"request_id": request_id},
    )


@router.get(
    "/users/roles",
    response_model=ApiResponse,
    summary="List user role assignments",
)
async def admin_list_user_roles(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """List current user-to-role mappings from security config."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()

    return ApiResponse(
        success=True,
        data={
            "user_roles": config.security.user_roles,
            "default_role": "viewer",
        },
        metadata={"request_id": request_id},
    )
