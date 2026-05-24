"""Manual gate reviewer — human-in-the-loop step-by-step approval via HTTP.

Persists a GateRequest row, blocks on an asyncio.Event keyed by request_id,
unblocks when a client POSTs a decision via the HTTP API. The mode is named
for *who* decides (a human, manually, one step at a time) — the HTTP-backed
plumbing is implementation detail.

Use case: a human approves / rejects / skips / retries each gate point via
CLI (`mc gate approve <id>`), TUI, or any other client of the gate API.
Distinct from `interactive` mode (Rich CLI prompt, TTY-bound) — manual mode
works from any client and survives backend restart-of-non-dispatcher
processes (the row persists; only the in-process Event is lost).

Design:
- Process-local in-memory registry of asyncio.Events keyed by GateRequest id.
- The endpoint that records the decision fires the Event so this coroutine
  can read it back and return.
- Single-process by design — Mission Control runs as one backend process.
  If multi-process is ever needed, swap the registry for a Redis pub-sub
  channel; the rest of the design is unchanged.

Timeout policy: if no decision arrives within ``timeout_seconds``, the row
is marked TIMED_OUT and the reviewer returns ``GateDecision(action=ABORT)``
so the dispatcher halts safely rather than running unapproved work.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from modules.backend.agents.mission_control.gate_models import (
    GateAction,
    GateContext,
    GateDecision,
)
from modules.backend.core.logging import get_logger
from modules.backend.models.gate_request import GateRequest, GateRequestStatus

logger = get_logger(__name__)


# Process-local registry: gate_request_id (str) -> asyncio.Event.
# Populated when a GateRequest is opened, fired when /decide arrives,
# popped when the awaiter returns. Single-process; see module docstring.
_PENDING: dict[str, asyncio.Event] = {}
_LOCK = asyncio.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively serialise dataclasses + dicts for JSONB storage."""
    if is_dataclass(obj):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(v) for v in obj]
    return obj


async def _fire_decision(request_id: str) -> None:
    """Called by the /decide endpoint to unblock the waiting reviewer."""
    async with _LOCK:
        event = _PENDING.get(request_id)
    if event is not None:
        event.set()


class ManualGateReviewer:
    """Persists a pause + blocks until an external client decides via HTTP."""

    def __init__(
        self,
        *,
        session_factory,        # callable returning an AsyncSession context manager
        timeout_seconds: int = 1800,
    ):
        """session_factory yields ``AsyncSession`` instances. The reviewer
        opens short-lived sessions for the create-row and read-back steps
        so it doesn't hold a connection while waiting on the asyncio.Event.
        """
        self._session_factory = session_factory
        self._timeout_seconds = timeout_seconds

    async def review(self, context: GateContext) -> GateDecision:
        request_id = str(uuid.uuid4())
        event = asyncio.Event()

        async with _LOCK:
            _PENDING[request_id] = event

        try:
            await self._persist_pending(request_id, context)
            logger.info(
                "Manual gate paused — awaiting decision",
                extra={
                    "request_id": request_id,
                    "gate_type": context.gate_type,
                    "mission_id": context.mission_id,
                    "timeout_seconds": self._timeout_seconds,
                },
            )

            try:
                await asyncio.wait_for(event.wait(), timeout=self._timeout_seconds)
            except asyncio.TimeoutError:
                await self._persist_timeout(request_id)
                logger.warning(
                    "Manual gate timed out — aborting for safety",
                    extra={"request_id": request_id, "gate_type": context.gate_type},
                )
                return GateDecision(
                    action=GateAction.ABORT,
                    reason=f"manual gate timeout after {self._timeout_seconds}s",
                    reviewer=f"manual:timeout:{request_id}",
                )

            decision = await self._read_decision(request_id)
            logger.info(
                "Manual gate decision received",
                extra={
                    "request_id": request_id,
                    "gate_type": context.gate_type,
                    "action": decision.action.value if hasattr(decision.action, "value") else str(decision.action),
                },
            )
            return decision
        finally:
            async with _LOCK:
                _PENDING.pop(request_id, None)

    async def _persist_pending(
        self, request_id: str, context: GateContext,
    ) -> None:
        async with self._session_factory() as session:
            row = GateRequest(
                id=request_id,
                mission_id=context.mission_id,
                plan_id=None,           # GateContext has no plan_id; the dispatcher knows it
                gate_type=context.gate_type,
                context_json=_dataclass_to_dict(context),
                status=GateRequestStatus.PENDING,
                created_at=_utc_now(),
            )
            session.add(row)
            await session.commit()

    async def _persist_timeout(self, request_id: str) -> None:
        from sqlalchemy import update
        async with self._session_factory() as session:
            await session.execute(
                update(GateRequest)
                .where(GateRequest.id == request_id)
                .values(
                    status=GateRequestStatus.TIMED_OUT,
                    timed_out_at=_utc_now(),
                ),
            )
            await session.commit()

    async def _read_decision(self, request_id: str) -> GateDecision:
        from sqlalchemy import select
        async with self._session_factory() as session:
            result = await session.execute(
                select(GateRequest).where(GateRequest.id == request_id),
            )
            row = result.scalar_one_or_none()
            if row is None or row.decision_json is None:
                # Should not happen — the Event was fired so the row should be
                # populated. Fail loud rather than silently continue.
                raise RuntimeError(
                    f"Gate API decision unexpectedly missing for request {request_id}",
                )
            data = row.decision_json
            action_value = data.get("action", "abort")
            action = GateAction(action_value) if isinstance(action_value, str) else action_value
            return GateDecision(
                action=action,
                reason=data.get("reason"),
                modified_instructions=data.get("modified_instructions"),
                modified_inputs=data.get("modified_inputs"),
                reviewer=data.get("reviewer", f"manual:{request_id}"),
            )
