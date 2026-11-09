"""Manual gate reviewer — human-in-the-loop step-by-step approval via HTTP.

Persists a GateRequest row, then polls that row until a client records a
decision via the HTTP API. The mode is named for *who* decides (a human,
manually, one step at a time) — the HTTP-backed plumbing is implementation
detail.

Use case: a human approves / rejects / skips / retries each gate point via
CLI (`mc gate approve <id>`), TUI, web, or any other client of the gate API.
Distinct from `interactive` mode (Rich CLI prompt, TTY-bound) — manual mode
works from any client.

Design (Plan 88.0.13): the waiter runs in the Temporal worker process while
the decision arrives in the API process, so the reviewer polls the
``gate_requests`` row every ``poll_interval_seconds`` until it is DECIDED.
The database row is the only coupling between the two processes.

Timeout policy: if no decision arrives within ``timeout_seconds``, the row
is marked TIMED_OUT and the reviewer returns ``GateDecision(action=ABORT)``
so the dispatcher halts safely rather than running unapproved work.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from typing import Any

from modules.backend.agents.mission_control.gate_models import GateAction, GateContext, GateDecision
from modules.backend.core.logging import get_logger
from modules.backend.services.mission_plan import (
    GateRequestStatus,
    MissionPlanService,
)

logger = get_logger(__name__)


class ManualGateReviewer:
    """Persists a pause + blocks until an external client decides via HTTP."""

    def __init__(
        self,
        *,
        session_factory,  # callable returning an AsyncSession context manager
        timeout_seconds: int,
        poll_interval_seconds: int,
        event_bus: Any = None,  # optional SessionEventBus; emits GateRequestOpenedEvent
    ):
        """session_factory yields ``AsyncSession`` instances. The reviewer
        opens short-lived sessions for the create-row, poll and read-back
        steps so it doesn't hold a connection while waiting for a decision.
        """
        self._session_factory = session_factory
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._event_bus = event_bus

    async def review(self, context: GateContext) -> GateDecision:
        request_id = str(uuid.uuid4())

        await self._persist_pending(request_id, context)
        await self._emit_opened(request_id, context)
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
            await self._wait_for_decision(request_id, context.mission_id)
        except asyncio.TimeoutError:
            await self._persist_timeout(request_id)
            logger.warning(
                "Manual gate timed out — aborting for safety",
                extra={
                    "request_id": request_id,
                    "gate_type": context.gate_type,
                    "mission_id": context.mission_id,
                },
            )
            if self._event_bus is not None:
                from modules.backend.events.types import SystemEvent

                try:
                    await self._event_bus.publish(
                        SystemEvent(
                            session_id=context.session_id or context.mission_id,
                            source=f"manual_gate:{request_id}",
                            level="error",
                            message=(
                                f"Manual gate timed out after "
                                f"{self._timeout_seconds}s — mission aborted for safety."
                            ),
                            mission_id=context.mission_id,
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to emit gate-timeout SystemEvent",
                        exc_info=True,
                        extra={"request_id": request_id, "mission_id": context.mission_id},
                    )
            return GateDecision(
                action=GateAction.ABORT,
                reason=f"manual gate timeout after {self._timeout_seconds}s",
                reviewer=f"manual:timeout:{request_id}",
            )
        except asyncio.CancelledError:
            # Dispatcher coroutine was cancelled (mission abort, backend
            # shutdown, Temporal activity cancel). Mark the row CANCELLED
            # before re-raising so it doesn't sit PENDING forever.
            # best-effort — this re-raises; the caller (mission abort,
            # shutdown, or Temporal cancellation) owns visibility for
            # its own cancellation path.
            await self._persist_cancelled(request_id)
            logger.warning(
                "Manual gate cancelled mid-wait",
                extra={
                    "request_id": request_id,
                    "gate_type": context.gate_type,
                    "mission_id": context.mission_id,
                },
            )
            raise

        decision = await self._read_decision(request_id, mission_id=context.mission_id)
        logger.info(
            "Manual gate decision received",
            extra={
                "request_id": request_id,
                "gate_type": context.gate_type,
                "action": (
                    decision.action.value
                    if hasattr(decision.action, "value")
                    else str(decision.action)
                ),
            },
        )
        return decision

    async def _wait_for_decision(self, request_id: str, mission_id: str) -> None:
        """Poll the gate row until DECIDED; raise asyncio.TimeoutError at the deadline."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_seconds
        while loop.time() < deadline:
            await asyncio.sleep(self._poll_interval_seconds)
            async with self._session_factory() as session:
                row = await MissionPlanService(session).get_gate_request(mission_id, request_id)
            if row.status == GateRequestStatus.DECIDED:
                return
        raise asyncio.TimeoutError

    async def _persist_pending(
        self,
        request_id: str,
        context: GateContext,
    ) -> None:
        async with self._session_factory() as session:
            await MissionPlanService(session).create_gate_request(
                request_id,
                mission_id=context.mission_id,
                session_id=context.session_id,
                gate_type=context.gate_type,
                context_json=asdict(context),
            )
            await session.commit()

    async def _persist_timeout(self, request_id: str) -> None:
        async with self._session_factory() as session:
            await MissionPlanService(session).mark_gate_request_timed_out(request_id)
            await session.commit()

    async def _persist_cancelled(self, request_id: str) -> None:
        async with self._session_factory() as session:
            await MissionPlanService(session).mark_gate_request_cancelled(request_id)
            await session.commit()

    async def _emit_opened(self, request_id: str, context: GateContext) -> None:
        """Best-effort GateRequestOpenedEvent emission; never fail the gate."""
        if self._event_bus is None:
            return
        try:
            from modules.backend.events.types import GateRequestOpenedEvent

            await self._event_bus.publish(
                GateRequestOpenedEvent(
                    session_id=context.session_id or context.mission_id,
                    source=f"manual_gate:{request_id}",
                    request_id=request_id,
                    mission_id=context.mission_id,
                    gate_type=context.gate_type,
                    timeout_seconds=self._timeout_seconds,
                )
            )
        except Exception:
            # best-effort — this IS the event-emission path; there is
            # nowhere further to escalate to.
            logger.warning(
                "Failed to emit GateRequestOpenedEvent",
                exc_info=True,
                extra={"request_id": request_id, "mission_id": context.mission_id},
            )

    async def _read_decision(self, request_id: str, *, mission_id: str) -> GateDecision:
        from modules.backend.core.exceptions import NotFoundError

        async with self._session_factory() as session:
            try:
                row = await MissionPlanService(session).get_gate_request(mission_id, request_id)
            except NotFoundError:
                row = None
            if row is None or row.decision_json is None:
                # Should not happen — the row was DECIDED so the decision should
                # be populated. Fail loud rather than silently continue.
                raise RuntimeError(
                    f"Gate API decision unexpectedly missing for request {request_id}",
                )
            data = row.decision_json
            action_value = data.get("action", "abort")
            action = GateAction(action_value) if isinstance(action_value, str) else action_value
            return GateDecision(
                action=action,
                reason=data.get("reason"),
                reviewer=data.get("reviewer", f"manual:{request_id}"),
            )
