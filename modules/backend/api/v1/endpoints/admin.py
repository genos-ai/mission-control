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

from modules.backend.core.config import get_app_config
from modules.backend.core.dependencies import AdminRole, DbSession, RequestId
from modules.backend.core.exceptions import AuthorizationError, ValidationError
from modules.backend.schemas.agent_config import Visibility
from modules.backend.schemas.base import ApiResponse

router = APIRouter()


def _load_models_registry() -> dict[str, list[str]]:
    """Valid {provider: [models]} from the model registry (config/settings/models.yaml)."""
    return get_app_config().models.models_by_provider()


def _model_is_valid(name: str, registry: dict[str, list[str]]) -> bool:
    """Check that `name` is a known provider:model combination."""
    if ":" not in name:
        return False
    provider, model = name.split(":", 1)
    return model in registry.get(provider, [])


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
    chat_enabled: bool = False
    visibility: Visibility | None = None
    model_config_json: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    interface: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    engine: str = "pydantic_ai"
    effort: str | None = None


class CatalogUpdateRequest(BaseModel):
    description: str | None = None
    enabled: bool | None = None
    chat_enabled: bool | None = None
    visibility: Visibility | None = None
    version: str | None = None
    tools: list[str] | None = None
    keywords: list[str] | None = None
    model_config_json: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    interface: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    engine: str | None = None
    effort: str | None = None
    thinking_budget_json: dict[str, Any] | None = Field(
        None, description="Extended thinking config, e.g. {max_thinking_tokens: 10000}"
    )


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
    from modules.backend.schemas.agent_catalog import AgentCatalogResponse
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    entries = await service.list_catalog(enabled_only=enabled_only)

    return ApiResponse(
        success=True,
        data={
            "agents": [AgentCatalogResponse.model_validate(e).model_dump() for e in entries],
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
        chat_enabled=body.chat_enabled,
        visibility=body.visibility,
        model_config_json=body.model_config_json,
        scope=body.scope,
        interface=body.interface,
        constraints=body.constraints,
        engine=body.engine,
        effort=body.effort,
    )

    return ApiResponse(
        success=True,
        data={"id": entry.id, "agent_name": entry.agent_name},
        metadata={"request_id": request_id},
    )


@router.get(
    "/models",
    response_model=ApiResponse,
    summary="List valid provider/model combinations",
)
async def admin_models_list(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Return the valid {provider: [models]} registry."""
    return ApiResponse(
        success=True,
        data={"models": _load_models_registry()},
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
    """Update fields on an existing agent catalog entry.

    Changing the agent's model/provider (`model_config_json.name`) is
    restricted to sysadmins and validated against the model registry.
    """
    from modules.backend.services.agent_catalog import AgentCatalogService

    service = AgentCatalogService(db)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    # Sysadmin gate + registry validation for model/provider changes.
    new_cfg = updates.get("model_config_json")
    if isinstance(new_cfg, dict) and "name" in new_cfg:
        new_name = new_cfg.get("name")
        existing = await service.get_by_name(agent_name)
        existing_name = (existing.model_config_json or {}).get("name")
        if new_name != existing_name:
            if not _role.has_role("sysadmin"):
                raise AuthorizationError(
                    "Changing the agent's model/provider requires sysadmin role."
                )
            if new_name and not _model_is_valid(new_name, _load_models_registry()):
                raise ValidationError(
                    f"Model '{new_name}' is not in the registry. "
                    f"See GET /admin/models for valid combinations."
                )

    entry = await service.update_entry(agent_name, **updates)

    # Reload registry so running agents pick up changes immediately
    from modules.backend.agents.mission_control.registry import get_registry

    get_registry().reload()

    return ApiResponse(
        success=True,
        data={
            "id": entry.id,
            "agent_name": entry.agent_name,
            "updated_fields": list(updates.keys()),
        },
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

    # Invalidate the registry cache so the next agent.run() picks up
    # the new prompt without a server restart.
    from modules.backend.agents.mission_control.registry import get_registry

    get_registry().reload()

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
    reset_prompts: bool = False,
) -> ApiResponse:
    """Seed the agent catalog from config/agents/ YAML files."""
    from modules.backend.services.agent_catalog import AgentCatalogService
    from modules.backend.services.catalog_seeder import seed_catalog

    service = AgentCatalogService(db)
    result = await seed_catalog(service, force=force, reset_prompts=reset_prompts)

    from modules.backend.agents.mission_control.registry import get_registry

    get_registry().reload()

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


# ---- Token Economics (Plan 60) ----


@router.get(
    "/metrics/token-economics",
    response_model=ApiResponse,
    summary="Token breakdown by agent",
)
async def admin_token_breakdown(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
) -> ApiResponse:
    """Per-agent token breakdown with cost attribution."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_token_breakdown(timeframe=timeframe)
    summary = await service.get_summary(timeframe=timeframe)

    return ApiResponse(
        success=True,
        data={"agents": data, "summary": summary},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/cache-performance",
    response_model=ApiResponse,
    summary="Cache hit rates and savings",
)
async def admin_cache_performance(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
) -> ApiResponse:
    """Per-agent cache hit rate and write-to-read ratio."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_cache_performance(timeframe=timeframe)

    return ApiResponse(
        success=True,
        data={"agents": data},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/cost-timeline",
    response_model=ApiResponse,
    summary="Cost timeline for charts",
)
async def admin_cost_timeline(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
    group_by: str = "agent",
) -> ApiResponse:
    """Hourly cost aggregation for time-series charts."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_cost_timeline(timeframe=timeframe, group_by=group_by)

    return ApiResponse(
        success=True,
        data={"timeline": data},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/expensive-calls",
    response_model=ApiResponse,
    summary="Most expensive LLM calls",
)
async def admin_expensive_calls(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
    limit: int = 20,
) -> ApiResponse:
    """Top N most expensive individual LLM calls."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_expensive_calls(limit=limit, timeframe=timeframe)

    return ApiResponse(
        success=True,
        data={"calls": data},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/model-distribution",
    response_model=ApiResponse,
    summary="Model usage distribution",
)
async def admin_model_distribution(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
) -> ApiResponse:
    """Call count and cost percentage per model."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_model_distribution(timeframe=timeframe)

    return ApiResponse(
        success=True,
        data={"models": data},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/output-efficiency",
    response_model=ApiResponse,
    summary="Output/input ratio by agent",
)
async def admin_output_efficiency(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
    timeframe: str = "7d",
) -> ApiResponse:
    """Per-agent output/input ratio — high ratio = expensive."""
    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    data = await service.get_output_efficiency(timeframe=timeframe)

    return ApiResponse(
        success=True,
        data={"agents": data},
        metadata={"request_id": request_id},
    )


@router.get(
    "/metrics/cost-alerts",
    response_model=ApiResponse,
    summary="Active cost alerts",
)
async def admin_cost_alerts(
    db: DbSession,
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """Check all cost alert rules and return any that triggered."""
    from modules.backend.services.cost_alerts import CostAlertService

    service = CostAlertService(db)
    alerts = await service.check_alerts()

    return ApiResponse(
        success=True,
        data={
            "alerts": [
                {"rule": a.rule, "message": a.message, "severity": a.severity} for a in alerts
            ],
            "count": len(alerts),
        },
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
                    **({"detail": c.detail} if c.detail else {}),
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

    from modules.backend.core.config import get_redis_url
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


@router.post(
    "/dispatch/emergency-stop",
    response_model=ApiResponse,
    summary="Emergency stop — pause all active autonomous plans",
)
async def admin_emergency_stop(
    request_id: RequestId,
    _role: AdminRole,
    db: DbSession,
) -> ApiResponse:
    """Atomically pause every active autonomous plan.

    Sets ``status = paused`` on all ``mission_plans`` rows where
    ``status = active`` AND ``gate_mode = autonomous``.
    This is a single UPDATE query — no per-plan loop, no race window.

    Use this when something is wrong and you need all autonomous
    dispatch to stop immediately. The daemon's next tick will see
    zero active plans and idle. Paused plans can be individually
    re-activated via the Plan tab or API once the situation is
    resolved.

    Does NOT cancel in-flight Temporal workflows — those must be
    cancelled via the Temporal CLI if needed. This endpoint prevents
    NEW dispatch cycles from starting.
    """
    from modules.backend.core.logging import get_logger
    from modules.backend.services.mission_plan import MissionPlanService

    logger = get_logger(__name__)

    paused_count = await MissionPlanService(db).pause_all_autonomous_plans()
    await db.commit()

    logger.warning(
        "EMERGENCY STOP: paused all autonomous plans",
        extra={"paused_count": paused_count, "request_id": request_id},
    )

    return ApiResponse(
        success=True,
        data={
            "paused_count": paused_count,
            "message": (
                f"Emergency stop: {paused_count} autonomous plan(s) paused. "
                f"Daemon will idle on next tick. Re-activate plans "
                f"individually when safe."
            ),
        },
        metadata={"request_id": request_id},
    )
