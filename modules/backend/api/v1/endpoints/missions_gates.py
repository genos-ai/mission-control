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
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from modules.backend.agents.mission_control.gate_manual import fire_decision
from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    get_event_bus,
    require_mission_access,
)
from modules.backend.events.bus import SessionEventBus
from modules.backend.events.types import GateRequestDecidedEvent
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.schemas.base import ApiResponse

EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]

router = APIRouter()


# =============================================================================
# Request / response models
# =============================================================================


class GateDecisionSubmission(BaseModel):
    """Body for POST /gates/{rid}/decide.

    The action vocabulary is union of the standard gate actions and the
    post_run autonomy-loop actions. The endpoint validates that the
    submitted action is appropriate for the gate's gate_type — e.g. you
    cannot submit `advance_refine` for a `pre_layer` gate.
    """

    action: Literal[
        # Standard gate actions (pre_dispatch, pre_layer, post_task,
        # verification_failed, post_layer):
        "continue",
        "skip",
        "retry",
        "abort",
        # post_run autonomy-loop actions:
        "wait",
        "advance_approved",
        "advance_refine",
        "propose_complete",
        "escalate",
    ] = Field(
        ...,
        description=(
            "Standard: continue (approve), skip, retry, abort. "
            "post_run: wait, advance_approved, advance_refine, "
            "propose_complete, escalate. `modify` is intentionally NOT "
            "exposed here — it requires modified_instructions plumbing "
            "that isn't end-to-end yet (Plan 80g v2)."
        ),
    )
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Optional reviewer note attached to the decision.",
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
    await require_mission_access(db, mission_id, current_user)
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
    await require_mission_access(db, mission_id, current_user)
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
    event_bus: EventBus,
) -> ApiResponse:
    """Record the decision and fire the asyncio.Event that unblocks the dispatcher.

    Fails with 409 if the request is not PENDING (already decided / timed out
    / cancelled). The dispatcher's `await event.wait()` was scoped before the
    DB row was written; firing the event here is what wakes it up.
    """
    await require_mission_access(db, mission_id, current_user)
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

    _validate_action_for_gate_type(row.gate_type, body.action)

    decision_payload = {
        "action": body.action,
        "reason": body.reason,
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
    await fire_decision(request_id_path)

    # Emit lifecycle event so watchers (TUI / console) see the resolution.
    try:
        await event_bus.publish(
            GateRequestDecidedEvent(
                session_id=row.session_id or row.mission_id,
                source=f"manual_gate:{request_id_path}",
                request_id=request_id_path,
                mission_id=row.mission_id,
                gate_type=row.gate_type,
                action=body.action,
                reason=body.reason,
                reviewer=f"user:{current_user.id}",
            )
        )
    except Exception:
        # Event-bus failures must not fail the decision response — the
        # decision is already committed. Log and continue.
        from modules.backend.core.logging import get_logger

        get_logger(__name__).warning(
            "Failed to emit GateRequestDecidedEvent",
            exc_info=True,
            extra={"request_id": request_id_path},
        )

    return ApiResponse(
        success=True,
        data={"id": request_id_path, "action": body.action},
        metadata={"request_id": request_id},
    )


# =============================================================================
# Helpers
# =============================================================================


_STANDARD_ACTIONS: frozenset[str] = frozenset(
    {"continue", "skip", "retry", "abort"},
)
_POST_RUN_ACTIONS: frozenset[str] = frozenset(
    {"wait", "advance_approved", "advance_refine", "propose_complete", "escalate"},
)


def _validate_action_for_gate_type(gate_type: str, action: str) -> None:
    """Reject actions that don't belong to the gate's vocabulary.

    Mixing the two action sets (e.g. `advance_refine` for a `pre_layer`
    gate or `continue` for a `post_run` gate) is silent corruption — the
    consumer of the decision wouldn't know what to do. Fail loud at the
    boundary instead.
    """
    if gate_type == "post_run":
        valid = _POST_RUN_ACTIONS
    else:
        valid = _STANDARD_ACTIONS
    if action not in valid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Action {action!r} is not valid for gate_type {gate_type!r}. "
                f"Valid actions: {sorted(valid)}."
            ),
        )


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
