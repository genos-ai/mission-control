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

    from modules.backend.schemas.agent_catalog import AgentCatalogResponse

    service = AgentCatalogService(db)
    entries = await service.list_catalog(enabled_only=enabled_only)

    return ApiResponse(
        success=True,
        data={
            "agents": [
                AgentCatalogResponse.model_validate(e).model_dump()
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
    await service.delete_entry(agent_name)

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
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    versions = await service.get_prompt_history(agent_name)

    return ApiResponse(
        success=True,
        data={
            "agent_name": agent_name,
            "versions": [
                {
                    "version": v.version,
                    "changed_by": v.changed_by,
                    "change_reason": v.change_reason,
                    "content_length": v.content_length,
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
    from modules.backend.core.config import get_sanitized_config_view

    return ApiResponse(
        success=True,
        data=get_sanitized_config_view(),
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
    from modules.backend.services.health import HealthCheckService

    service = HealthCheckService()
    report = await service.check_readiness()

    return ApiResponse(
        success=True,
        data={
            "status": report.overall_status,
            "checks": {
                c.name: {
                    "status": c.status,
                    **({"latency_ms": c.latency_ms} if c.latency_ms is not None else {}),
                    **({"error": c.error} if c.error else {}),
                }
                for c in report.components
            },
        },
        metadata={"request_id": request_id},
    )


# ---- Daemon liveness (Plan 46 Phase 1 #3) ----


# Seconds before a heartbeat counts as stale. Matches the Plan 46
# Phase 1 exit criterion ("less than 30 seconds old") — looser than
# the daemon's own 20-second heartbeat TTL so operators have a
# definitive yes/no without race conditions around Redis key expiry.
_DAEMON_ALIVE_THRESHOLD_SEC = 30.0


@router.get(
    "/daemon/status",
    response_model=ApiResponse,
    summary="Mission plan daemon liveness status",
)
async def admin_daemon_status(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Return the mission plan daemon's most recent heartbeat.

    The daemon (``modules/backend/services/mission_plan_daemon.py``)
    writes a JSON heartbeat to Redis every poll cycle. This endpoint
    reads that key back and derives three things:

      - ``enabled``: whether the daemon feature flag is on. If false,
        the rest of the fields are meaningless — the daemon isn't
        running on this process.
      - ``alive``: whether the heartbeat is fresh. A heartbeat older
        than ``_DAEMON_ALIVE_THRESHOLD_SEC`` counts as stale, so the
        daemon is considered dead even if the key still exists (the
        key's own TTL is a shorter backup).
      - ``last_heartbeat_at`` / ``last_heartbeat_age_sec`` /
        ``tick_count`` / ``last_error``: raw heartbeat payload for
        observability.

    Used by ops to confirm the autonomous dispatch loop is actually
    running, and by ``scripts/verify_daemon_heartbeat.py`` as the
    acceptance check for Plan 46 Phase 1 work unit #3.
    """
    from datetime import datetime

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_app_config, get_redis_url
    from modules.backend.core.utils import utc_now
    from modules.backend.services.mission_plan_daemon import get_heartbeat

    app_config = get_app_config()
    enabled = app_config.features.experimental_mission_plan_daemon_enabled

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        heartbeat = await get_heartbeat(redis)
    finally:
        await redis.aclose()

    if heartbeat is None:
        return ApiResponse(
            success=True,
            data={
                "enabled": enabled,
                "alive": False,
                "last_heartbeat_at": None,
                "last_heartbeat_age_sec": None,
                "tick_count": None,
                "last_error": None,
                "poll_interval_sec": None,
            },
            metadata={"request_id": request_id},
        )

    # Both `utc_now()` and the daemon's persisted timestamp are
    # timezone-naive by codebase convention (core/utils.py::utc_now).
    # Stay naive throughout; a direct subtraction is valid.
    last_at_str = str(heartbeat.get("timestamp") or "")
    try:
        last_at = datetime.fromisoformat(last_at_str)
    except ValueError:
        last_at = None

    age_sec: float | None = None
    alive = False
    if last_at is not None:
        age_sec = (utc_now() - last_at).total_seconds()
        alive = age_sec < _DAEMON_ALIVE_THRESHOLD_SEC

    return ApiResponse(
        success=True,
        data={
            "enabled": enabled,
            "alive": alive,
            "last_heartbeat_at": last_at_str,
            "last_heartbeat_age_sec": age_sec,
            "tick_count": heartbeat.get("tick_count"),
            "poll_interval_sec": heartbeat.get("poll_interval_sec"),
            "last_error": heartbeat.get("last_error"),
        },
        metadata={"request_id": request_id},
    )


