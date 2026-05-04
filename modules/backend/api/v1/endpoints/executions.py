"""
Execution Record API endpoints.

Read endpoints for querying execution history,
decisions, and cost breakdowns. Write operations happen via
the ExecutionPersistenceService called from the dispatch loop.

Temporal endpoints (execute, approve, status) are gated by
the temporal.enabled feature flag.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, Idempotency, RequestId
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

    Reads from execution_records only — the single source of truth
    for all runs (Plan 71).
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

    items = [
        ExecutionRecordResponse.model_validate(e).model_copy(
            update={"task_count": len(e.task_executions or [])}
        )
        for e in executions
    ]

    return ApiResponse(
        success=True,
        data=ExecutionListResponse(
            executions=items,
            total=total,
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

    Reads from execution_records only (Plan 71).
    """
    service = ExecutionPersistenceService(db)
    execution = await service.get_execution(execution_id)

    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    response = ExecutionRecordDetailResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
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
    idempotency: Idempotency,
) -> ApiResponse:
    """Start an execution — returns immediately, runs in background.

    The execution dispatches asynchronously. Monitor progress via
    SSE at GET /streams/runs/{session_id}.

    Supports Idempotency-Key header — safe to retry on network timeout.
    """
    # Return cached response if this execution was already started
    if idempotency:
        cached = await idempotency.get_cached_response()
        if cached:
            return ApiResponse(**cached)

    import asyncio

    from modules.backend.core.config import get_app_config

    config = get_app_config()
    service = ExecutionPersistenceService(db)

    record = await service.get_execution(execution_id)
    if not record:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    if config.temporal.enabled:
        from modules.backend.core.exceptions import ApplicationError
        from modules.backend.core.config import get_default_budget_usd
        from modules.backend.temporal.client import get_temporal_client
        from modules.backend.temporal.models import MissionWorkflowInput
        from modules.backend.temporal.workflow import AgentMissionWorkflow

        if not record.mission_id:
            raise ApplicationError(f"Execution record '{execution_id}' has no mission_id")
        if not record.session_id:
            raise ApplicationError(f"Execution record '{execution_id}' has no session_id")

        client = await get_temporal_client()
        handle = await client.start_workflow(
            AgentMissionWorkflow.run,
            MissionWorkflowInput(
                mission_run_id=execution_id,
                session_id=record.session_id,
                mission_brief=record.objective_statement or "",
                roster_name=record.roster_name or "default",
                mission_budget_usd=get_default_budget_usd(),
                mission_id=record.mission_id,
                approval_timeout_seconds=config.temporal.approval_timeout_seconds,
                escalation_timeout_seconds=config.temporal.escalation_timeout_seconds,
                notification_timeout_seconds=config.temporal.notification_timeout_seconds,
            ),
            id=f"execution-{execution_id}",
            task_queue=config.temporal.task_queue,
        )
        result = {
            "workflow_id": handle.id,
            "execution_id": execution_id,
            "status": "started",
        }
        response = ApiResponse(
            success=True,
            data=result,
            metadata={"request_id": request_id},
        )
        if idempotency:
            await idempotency.cache_response(response.model_dump())
        return response

    # Non-Temporal: fire-and-forget via handle_mission (Plan 71)

    _bg_mission_id = record.mission_id

    async def _run_in_background(exec_id: str) -> None:
        from modules.backend.agents.mission_control.mission_dispatch import handle_mission
        from modules.backend.agents.mission_control.models import NoOpEventBus
        from modules.backend.core.config import get_default_budget_usd, get_redis_url
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session import SessionService
        from redis.asyncio import Redis as AsyncRedis

        try:
            redis = AsyncRedis.from_url(get_redis_url())
            from modules.backend.events.bus import SessionEventBus
            event_bus = SessionEventBus(redis, mission_id=_bg_mission_id)

            async with get_async_session() as bg_db:
                svc = ExecutionPersistenceService(bg_db)
                rec = await svc.get_execution(exec_id)
                if not rec:
                    return

                session_svc = SessionService(bg_db)
                await handle_mission(
                    mission_run_id=f"mission-{rec.session_id}",
                    mission_brief=rec.objective_statement or "",
                    session_service=session_svc,
                    event_bus=event_bus,
                    roster_name=rec.roster_name or "default",
                    mission_budget_usd=get_default_budget_usd(),
                    session_id=rec.session_id,
                    mission_id=rec.mission_id,
                    db_session=bg_db,
                    execution_record_id=exec_id,
                )
                await bg_db.commit()
        except Exception:
            logger.exception("Background execution failed", extra={"execution_id": exec_id})

    asyncio.create_task(_run_in_background(execution_id))

    response = ApiResponse(
        success=True,
        data={
            "id": str(record.id),
            "status": "running",
            "objective": record.objective_statement,
        },
        metadata={"request_id": request_id},
    )
    if idempotency:
        await idempotency.cache_response(response.model_dump())
    return response


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
    """Cancel a pending or running execution via execution_records (Plan 71)."""
    service = ExecutionPersistenceService(db)
    record = await service.get_execution(execution_id)
    if not record:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    status = record.status.value if hasattr(record.status, "value") else str(record.status)
    if status.lower() in ("completed", "failed", "cancelled", "timed_out"):
        return ApiResponse(
            success=True,
            data={"id": str(record.id), "status": status, "message": "Already terminal"},
            metadata={"request_id": request_id},
        )

    await service.complete_execution(
        execution_record_id=str(record.id),
        status="cancelled",
    )
    await db.commit()
    return ApiResponse(
        success=True,
        data={"id": str(record.id), "status": "cancelled"},
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
