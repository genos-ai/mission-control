"""Manual-gate review API endpoints (Plan 80g).

When a mission runs with `gate_mode=manual`, every gate point (pre_dispatch,
pre_layer, post_task, verification_failed, post_layer) parks a row in
`gate_requests` and blocks the dispatcher on an asyncio.Event. These
endpoints let an external client (CLI / TUI / script) list pending gates,
inspect their context, and POST a decision that unblocks the dispatcher.

Endpoints:
    GET  /missions/{mid}/gates/pending           — list pending gate requests
    GET  /missions/{mid}/gates/{rid}             — full context for one
    POST /missions/{mid}/gates/{rid}/decide      — submit a decision
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from modules.backend.agents.mission_control.gate_manual import _fire_decision
from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.schemas.base import ApiResponse

router = APIRouter()


# =============================================================================
# Request / response models
# =============================================================================


class GateDecisionSubmission(BaseModel):
    """Body for POST /gates/{rid}/decide."""

    action: Literal[
        "continue", "skip", "retry", "abort", "modify",
    ] = Field(
        ...,
        description=(
            "Standard actions: continue (approve), skip, retry, abort. "
            "`modify` accepts a payload via modified_instructions / "
            "modified_inputs but is reserved for future use."
        ),
    )
    reason: str | None = Field(
        None, max_length=2000,
        description="Optional reviewer note attached to the decision.",
    )
    modified_instructions: str | None = Field(
        None, max_length=10000,
        description="When action=modify, replacement instructions for the task.",
    )
    modified_inputs: dict[str, Any] | None = Field(
        None,
        description="When action=modify, replacement inputs for the task.",
    )


class GateRequestSummary(BaseModel):
    """Compact gate request shape for list responses."""

    id: str
    mission_id: str
    plan_id: str | None
    gate_type: str
    status: str
    created_at: str
    decided_at: str | None = None


class GateRequestDetail(GateRequestSummary):
    """Full gate request shape (includes context_json + decision_json)."""

    context_json: dict[str, Any]
    decision_json: dict[str, Any] | None = None
    timed_out_at: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/{mission_id}/gates/pending",
    response_model=ApiResponse,
    summary="List pending gate requests for a mission",
)
async def list_pending_gates(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Return all gate requests in PENDING status, oldest first."""
    result = await db.execute(
        select(GateRequest)
        .where(
            GateRequest.mission_id == mission_id,
            GateRequest.status == GateRequestStatus.PENDING,
        )
        .order_by(GateRequest.created_at.asc()),
    )
    rows = result.scalars().all()
    items = [
        GateRequestSummary(
            id=str(r.id),
            mission_id=str(r.mission_id),
            plan_id=str(r.plan_id) if r.plan_id else None,
            gate_type=r.gate_type,
            status=str(r.status.value if hasattr(r.status, "value") else r.status),
            created_at=r.created_at.isoformat(),
            decided_at=r.decided_at.isoformat() if r.decided_at else None,
        ).model_dump()
        for r in rows
    ]
    return ApiResponse(
        success=True,
        data={"gates": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/gates/{request_id_path}",
    response_model=ApiResponse,
    summary="Get full context of one gate request",
)
async def get_gate_request(
    mission_id: str,
    request_id_path: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Read one gate request including its serialised GateContext."""
    row = await _load_gate(db, mission_id, request_id_path)
    detail = GateRequestDetail(
        id=str(row.id),
        mission_id=str(row.mission_id),
        plan_id=str(row.plan_id) if row.plan_id else None,
        gate_type=row.gate_type,
        status=str(row.status.value if hasattr(row.status, "value") else row.status),
        created_at=row.created_at.isoformat(),
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        timed_out_at=row.timed_out_at.isoformat() if row.timed_out_at else None,
        context_json=row.context_json,
        decision_json=row.decision_json,
    )
    return ApiResponse(
        success=True,
        data=detail.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/gates/{request_id_path}/decide",
    response_model=ApiResponse,
    summary="Submit a decision for a pending gate",
)
async def decide_gate(
    mission_id: str,
    request_id_path: str,
    body: GateDecisionSubmission,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Record the decision and fire the asyncio.Event that unblocks the dispatcher.

    Fails with 409 if the request is not PENDING (already decided / timed out
    / cancelled). The dispatcher's `await event.wait()` was scoped before the
    DB row was written; firing the event here is what wakes it up.
    """
    row = await _load_gate(db, mission_id, request_id_path)

    current_status = row.status.value if hasattr(row.status, "value") else row.status
    if str(current_status) != GateRequestStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Gate request {request_id_path} is not pending "
                f"(current status: {current_status})."
            ),
        )

    decision_payload = {
        "action": body.action,
        "reason": body.reason,
        "modified_instructions": body.modified_instructions,
        "modified_inputs": body.modified_inputs,
        "reviewer": f"user:{current_user.id}",
    }

    await db.execute(
        update(GateRequest)
        .where(GateRequest.id == request_id_path)
        .values(
            status=GateRequestStatus.DECIDED,
            decision_json=decision_payload,
            decided_by_user_id=current_user.id,
            decided_at=datetime.now(timezone.utc),
        ),
    )
    await db.commit()

    # Wake the waiting dispatcher (process-local asyncio.Event).
    await _fire_decision(request_id_path)

    return ApiResponse(
        success=True,
        data={"id": request_id_path, "action": body.action},
        metadata={"request_id": request_id},
    )


# =============================================================================
# Helpers
# =============================================================================


async def _load_gate(db: Any, mission_id: str, request_id: str) -> GateRequest:
    result = await db.execute(
        select(GateRequest).where(
            GateRequest.id == request_id,
            GateRequest.mission_id == mission_id,
        ),
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Gate request {request_id} not found for mission {mission_id}.",
        )
    return row
