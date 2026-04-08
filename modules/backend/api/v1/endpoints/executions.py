"""
Execution Record API endpoints.

Read endpoints for querying execution history,
decisions, and cost breakdowns. Write operations happen via
the ExecutionPersistenceService called from the dispatch loop.

Temporal endpoints (execute, approve, status) are gated by
the temporal.enabled feature flag.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.execution_record import (
    ExecutionCostBreakdown,
    ExecutionDecisionResponse,
    ExecutionListResponse,
    ExecutionRecordDetailResponse,
    ExecutionRecordResponse,
)
from modules.backend.services.execution_persistence import ExecutionPersistenceService

router = APIRouter()


@router.get("", response_model=ApiResponse, summary="List execution records")
async def list_executions(
    db: DbSession,
    request_id: RequestId,
    status: str | None = None,
    roster_name: str | None = None,
    objective_category: str | None = None,
    mission_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse:
    """List execution records with optional filters.

    Merges persisted records (execution_records) with live/in-flight
    runs (executions table) so newly started runs appear immediately.
    """
    service = ExecutionPersistenceService(db)
    executions, total = await service.list_executions(
        status=status,
        roster_name=roster_name,
        objective_category=objective_category,
        mission_id=mission_id,
        limit=limit,
        offset=offset,
    )

    persisted = [ExecutionRecordResponse.model_validate(e) for e in executions]

    # Merge live executions not yet persisted
    from modules.backend.services.execution import ExecutionService

    execution_svc = ExecutionService(db)
    live_runs = await execution_svc.list_live_executions(
        mission_id=mission_id, limit=50,
    )

    persisted_ids = {str(e.id) for e in executions}
    for live in live_runs:
        if str(live.id) in persisted_ids:
            continue
        # Apply status filter if given
        live_status = live.status.value if hasattr(live.status, "value") else str(live.status)
        if status and live_status.lower() != status.lower():
            continue
        from datetime import datetime as _dt

        def _parse_ts(val: object) -> _dt | None:
            if val is None:
                return None
            if isinstance(val, _dt):
                return val
            try:
                return _dt.fromisoformat(str(val).replace(" ", "T"))
            except (ValueError, TypeError):
                return None

        from modules.backend.core.utils import utc_now
        now = utc_now()
        persisted.append(ExecutionRecordResponse.model_validate({
            "id": str(live.id),
            "session_id": str(live.session_id),
            "roster_name": live.roster_ref,
            "status": live_status,
            "total_cost_usd": float(live.total_cost_usd or 0),
            "started_at": _parse_ts(live.started_at),
            "completed_at": _parse_ts(live.completed_at),
            "parent_execution_record_id": None,
            "created_at": _parse_ts(live.created_at) or now,
            "updated_at": _parse_ts(live.updated_at) or _parse_ts(live.created_at) or now,
        }))

    # Sort by created_at descending
    persisted.sort(key=lambda e: e.created_at or "", reverse=True)

    return ApiResponse(
        success=True,
        data=ExecutionListResponse(
            executions=persisted[:limit],
            total=total + len(persisted) - len(executions),
            page_size=limit,
            offset=offset,
        ).model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}",
    response_model=ApiResponse,
    summary="Get execution record detail",
)
async def get_execution(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get an execution record with full details.

    Checks both execution_records (post-run persistence) and
    executions (live/in-flight runs) so the frontend can display
    runs that are still in progress.
    """
    service = ExecutionPersistenceService(db)
    execution = await service.get_execution(execution_id)

    if execution:
        response = ExecutionRecordDetailResponse.model_validate(execution)
        return ApiResponse(
            success=True,
            data=response.model_dump(),
            metadata={"request_id": request_id},
        )

    # Fallback: check the live executions table
    from modules.backend.services.execution import ExecutionService

    execution_svc = ExecutionService(db)
    live = await execution_svc.get_execution_or_none(execution_id)

    if not live:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    # Map live execution to the detail response shape
    return ApiResponse(
        success=True,
        data={
            "id": str(live.id),
            "session_id": str(live.session_id),
            "roster_name": live.roster_ref,
            "status": live.status.value if hasattr(live.status, "value") else str(live.status),
            "total_cost_usd": float(live.total_cost_usd or 0),
            "started_at": str(live.started_at) if live.started_at else None,
            "completed_at": str(live.completed_at) if live.completed_at else None,
            "created_at": str(live.created_at) if live.created_at else None,
            "updated_at": str(live.updated_at) if live.updated_at else None,
            "parent_execution_record_id": None,
            "objective_statement": live.objective,
            "objective_category": None,
            "task_plan_json": None,
            "execution_outcome_json": None,
            "planning_thinking_trace": None,
            "task_executions": [],
            "decisions": [],
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/decisions",
    response_model=ApiResponse,
    summary="Get execution decision audit trail",
)
async def get_execution_decisions(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get the decision audit trail for an execution."""
    service = ExecutionPersistenceService(db)

    execution = await service.get_execution(execution_id)
    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    decisions = await service.get_decisions(execution_id)
    items = [
        ExecutionDecisionResponse.model_validate(d).model_dump()
        for d in decisions
    ]

    return ApiResponse(
        success=True,
        data={"decisions": items, "count": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/cost",
    response_model=ApiResponse,
    summary="Get execution cost breakdown",
)
async def get_execution_cost(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get detailed cost breakdown for an execution."""
    service = ExecutionPersistenceService(db)
    breakdown = await service.get_cost_breakdown(execution_id)

    return ApiResponse(
        success=True,
        data=breakdown.model_dump(),
        metadata={"request_id": request_id},
    )


# =============================================================================
# Execution dispatch
# =============================================================================


@router.post(
    "/{execution_id}/execute",
    response_model=ApiResponse,
    summary="Execute an execution",
)
async def execute_execution(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Start an execution — returns immediately, runs in background.

    The execution dispatches asynchronously. Monitor progress via
    SSE at GET /streams/runs/{session_id}.
    """
    import asyncio
    from modules.backend.core.config import get_app_config
    from modules.backend.services.execution import ExecutionService

    config = get_app_config()

    service = ExecutionService(session=db)

    if config.temporal.enabled:
        result = await service.start_temporal_execution(execution_id)
        return ApiResponse(
            success=True,
            data=result,
            metadata={"request_id": request_id},
        )

    # Load execution to return data immediately
    execution = await service.get_execution(execution_id)

    # Fire-and-forget: run dispatch in background task
    async def _run_in_background(exec_id: str) -> None:
        from modules.backend.agents.mission_control.dispatch_adapter import (
            MissionControlDispatchAdapter,
        )
        from modules.backend.services.session import SessionService
        from modules.backend.events.bus import SessionEventBus
        from modules.backend.core.config import get_redis_url
        from redis.asyncio import Redis as AsyncRedis

        try:
            redis = AsyncRedis.from_url(get_redis_url())
            event_bus = SessionEventBus(redis)

            async with ExecutionService.factory(event_bus=event_bus) as svc:
                await svc.run_execution(exec_id)
        except Exception:
            logger.exception("Background execution failed", extra={"execution_id": exec_id})

    asyncio.create_task(_run_in_background(execution_id))

    from modules.backend.schemas.execution import ExecutionResponse
    response = ExecutionResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{execution_id}/cancel",
    response_model=ApiResponse,
    summary="Cancel an execution",
)
async def cancel_execution(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
    reason: str = "Cancelled by user",
) -> ApiResponse:
    """Cancel a pending or running execution."""
    from modules.backend.services.execution import ExecutionService

    service = ExecutionService(db)

    execution = await service.get_execution_or_none(execution_id)
    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    status = execution.status.value if hasattr(execution.status, "value") else str(execution.status)
    if status in ("completed", "failed", "cancelled"):
        return ApiResponse(
            success=True,
            data={"id": str(execution.id), "status": status, "message": "Already terminal"},
            metadata={"request_id": request_id},
        )

    execution = await service.cancel_execution(execution_id, reason)

    return ApiResponse(
        success=True,
        data={"id": str(execution.id), "status": "cancelled"},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{execution_id}/approve",
    response_model=ApiResponse,
    summary="Submit approval for an execution",
)
async def submit_approval(
    execution_id: str,
    decision: str,
    responder_id: str,
    request_id: RequestId,
    reason: str | None = None,
) -> ApiResponse:
    """Send an approval decision to a waiting Temporal workflow."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()
    if not config.temporal.enabled:
        return ApiResponse(
            success=False,
            data={
                "error": "temporal_not_enabled",
                "message": "Approval signals require Temporal.",
            },
            metadata={"request_id": request_id},
        )

    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.models import ApprovalDecision
    from modules.backend.temporal.workflow import AgentMissionWorkflow

    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"execution-{execution_id}")

    await handle.signal(
        AgentMissionWorkflow.submit_approval,
        ApprovalDecision(
            decision=decision,
            responder_type="human",
            responder_id=responder_id,
            reason=reason,
        ),
    )

    return ApiResponse(
        success=True,
        data={
            "execution_id": execution_id,
            "decision": decision,
            "status": "signal_sent",
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/status",
    response_model=ApiResponse,
    summary="Get execution status",
)
async def get_execution_status(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get execution status — Temporal Query or DB fallback."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()

    if config.temporal.enabled:
        try:
            from modules.backend.temporal.client import get_temporal_client
            from modules.backend.temporal.workflow import AgentMissionWorkflow

            client = await get_temporal_client()
            handle = client.get_workflow_handle(f"execution-{execution_id}")
            status = await handle.query(AgentMissionWorkflow.get_status)
            return ApiResponse(
                success=True,
                data={
                    "source": "temporal",
                    "execution_id": status.mission_id,
                    "workflow_status": status.workflow_status,
                    "execution_status": status.mission_status,
                    "total_cost_usd": status.total_cost_usd,
                    "waiting_for_approval": status.waiting_for_approval,
                    "error": status.error,
                },
                metadata={"request_id": request_id},
            )
        except Exception as e:
            logger.debug(
                "Temporal status query failed, falling back to DB",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    service = ExecutionPersistenceService(db)
    try:
        status_dict = await service.get_execution_status(execution_id)
        return ApiResponse(
            success=True,
            data={"source": "database", **status_dict},
            metadata={"request_id": request_id},
        )
    except Exception as e:
        logger.warning(
            "Execution status lookup failed",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        raise NotFoundError(f"Execution '{execution_id}' not found")
