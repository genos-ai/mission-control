"""
Mission Console Event Aggregator.

Subscribes to Redis Pub/Sub channels for all sessions in a mission,
merges them into a single async stream, and classifies each event
into a console category (execution, chat, system).

Used by the Mission Console SSE endpoint to provide a unified,
real-time view of everything happening inside a mission.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger
from modules.backend.events.types import deserialize_event, SessionEvent
from modules.backend.models.session import Session

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

_EXECUTION_PATTERN = re.compile(
    r"^(plan\.|agent\.|workflow\.|convergence\.|session\.cost\.)"
)
_CHAT_PATTERN = re.compile(
    r"^(assistant\.message\.delta|assistant\.message\.complete|user\.message\.)"
)


async def get_console_history(
    db_session: "AsyncSession",
    mission_id: str,
    limit: int = 200,
) -> list[dict]:
    """Build a unified timeline of session messages and execution events.

    Queries all sessions belonging to this mission, collects their messages
    and execution records, and returns them sorted by timestamp descending.
    """
    from sqlalchemy.orm import selectinload

    from modules.backend.models.execution_record import (
        ExecutionDecision,
        ExecutionRecord,
        TaskAttempt,
        TaskExecution,
    )
    from modules.backend.models.session import Session, SessionMessage

    # 1. Get all session IDs for this mission
    session_ids_result = await db_session.execute(
        select(Session.id).where(Session.mission_id == mission_id)
    )
    session_ids = [row[0] for row in session_ids_result.all()]

    if not session_ids:
        return []

    timeline: list[dict] = []

    # 2. Fetch recent session messages
    messages_result = await db_session.execute(
        select(SessionMessage)
        .where(SessionMessage.session_id.in_(session_ids))
        .order_by(SessionMessage.created_at.desc())
        .limit(limit)
    )
    messages = messages_result.scalars().all()

    role_to_event_type = {
        "user": "user.message.sent",
        "assistant": "assistant.message.complete",
        "system": "system.message",
        "tool_call": "agent.tool.called",
        "tool_result": "agent.tool.returned",
    }

    for msg in messages:
        event_type = role_to_event_type.get(msg.role, f"{msg.role}.message")
        timeline.append({
            "event_id": str(msg.id),
            "event_type": event_type,
            "category": classify_event(event_type),
            "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            "source": msg.sender_id or msg.session_id,
            "data": {
                "session_id": msg.session_id,
                "role": msg.role,
                "content": msg.content,
                "model": msg.model,
                "input_tokens": msg.input_tokens,
                "output_tokens": msg.output_tokens,
                "cost_usd": msg.cost_usd,
                "tool_name": msg.tool_name,
                "tool_call_id": msg.tool_call_id,
                "thinking": msg.thinking,
            },
        })

    # 3. Fetch recent execution records with task details
    exec_result = await db_session.execute(
        select(ExecutionRecord)
        .where(ExecutionRecord.mission_id == mission_id)
        .options(
            selectinload(ExecutionRecord.task_executions)
            .selectinload(TaskExecution.attempts),
            selectinload(ExecutionRecord.decisions),
        )
        .order_by(ExecutionRecord.created_at.desc())
        .limit(limit)
    )
    records = exec_result.scalars().all()

    for rec in records:
        rec_status = rec.status if isinstance(rec.status, str) else rec.status.value
        timeline.append({
            "event_id": str(rec.id),
            "event_type": "execution.record",
            "category": "execution",
            "timestamp": str(rec.created_at) if rec.created_at else None,
            "source": rec.roster_name or rec.session_id,
            "data": {
                "session_id": rec.session_id,
                "status": rec_status,
                "roster_name": rec.roster_name,
                "objective_statement": rec.objective_statement,
                "objective_category": rec.objective_category,
                "total_cost_usd": rec.total_cost_usd,
                "started_at": rec.started_at,
                "completed_at": rec.completed_at,
            },
        })

        for te in rec.task_executions:
            te_status = te.status if isinstance(te.status, str) else te.status.value
            timeline.append({
                "event_id": str(te.id),
                "event_type": f"task.{te_status}",
                "category": "execution",
                "timestamp": str(te.completed_at or te.started_at or rec.created_at),
                "source": te.agent_name,
                "data": {
                    "task_id": te.task_id,
                    "agent_name": te.agent_name,
                    "status": te_status,
                    "cost_usd": te.cost_usd,
                    "duration_seconds": te.duration_seconds,
                    "verification_outcome": te.verification_outcome,
                    "output_data": te.output_data,
                    "attempt_count": len(te.attempts),
                },
            })

            for att in te.attempts:
                att_status = att.status if isinstance(att.status, str) else att.status.value
                if att_status == "failed":
                    timeline.append({
                        "event_id": str(att.id),
                        "event_type": "task.attempt.failed",
                        "category": "execution",
                        "timestamp": str(att.created_at) if att.created_at else str(rec.created_at),
                        "source": te.agent_name,
                        "data": {
                            "task_id": te.task_id,
                            "agent_name": te.agent_name,
                            "attempt_number": att.attempt_number,
                            "failure_tier": att.failure_tier if isinstance(att.failure_tier, str) else (att.failure_tier.value if att.failure_tier else None),
                            "failure_reason": att.failure_reason,
                            "cost_usd": att.cost_usd,
                        },
                    })

        for dec in rec.decisions:
            dec_type = dec.decision_type if isinstance(dec.decision_type, str) else dec.decision_type.value
            timeline.append({
                "event_id": str(dec.id),
                "event_type": f"decision.{dec_type}",
                "category": "execution",
                "timestamp": str(dec.created_at) if dec.created_at else str(rec.created_at),
                "source": "mission_control",
                "data": {
                    "decision_type": dec_type,
                    "task_id": dec.task_id,
                    "reasoning": dec.reasoning,
                },
            })

    # 4. Sort unified timeline by timestamp descending, then truncate
    timeline.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    return timeline[:limit]


def classify_event(event_type: str) -> str:
    """Assign a console category to an event type.

    Returns:
        One of ``execution``, ``chat``, or ``system``.
    """
    if _EXECUTION_PATTERN.match(event_type):
        return "execution"
    if _CHAT_PATTERN.match(event_type):
        return "chat"
    return "system"


# ---------------------------------------------------------------------------
# MissionEventAggregator
# ---------------------------------------------------------------------------


class MissionEventAggregator:
    """Aggregate real-time events from every session in a mission.

    The aggregator:
    1. Queries the DB for all sessions belonging to a mission.
    2. Subscribes to the Redis Pub/Sub channel for each session.
    3. Merges all channels into a single ``asyncio.Queue``.
    4. Re-queries sessions every ``refresh_interval`` seconds to pick up
       new sessions that were created after the aggregator started.
    """

    def __init__(
        self,
        redis: Redis,
        mission_id: str,
        refresh_interval: float = 30.0,
    ) -> None:
        self._redis = redis
        self._mission_id = mission_id
        self._refresh_interval = refresh_interval

        self._prefix = get_app_config().events.channel_prefix
        self._queue: asyncio.Queue[SessionEvent] = asyncio.Queue()

        # Tracks which session IDs we are already subscribed to
        self._subscribed_ids: set[str] = set()
        # One pubsub per session subscription
        self._pubsubs: list = []
        # Background tasks for each subscription reader + the refresh loop
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bootstrap subscriptions and start the refresh loop."""
        # Subscribe to mission-level channel for system events
        mission_channel = f"mission_events:{self._mission_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(mission_channel)
        self._pubsubs.append(pubsub)
        self._tasks.append(
            asyncio.create_task(
                self._read_pubsub(pubsub, mission_channel),
                name=f"console-mission-{self._mission_id[:8]}",
            )
        )

        # Subscribe to all existing session channels
        await self._refresh_sessions()
        self._tasks.append(
            asyncio.create_task(self._refresh_loop(), name="console-refresh")
        )

    async def stop(self) -> None:
        """Cancel all background tasks and clean up subscriptions."""
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        # Wait for tasks to actually finish (suppress CancelledError)
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for ps in self._pubsubs:
            try:
                await ps.unsubscribe()
                await ps.close()
            except Exception:
                pass
        logger.debug(
            "MissionEventAggregator stopped",
            extra={"mission_id": self._mission_id},
        )

    async def __aiter__(self) -> AsyncIterator[dict]:
        """Yield enriched event dicts as they arrive."""
        while not self._stopped:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            payload = json.loads(event.model_dump_json())
            payload["category"] = classify_event(event.event_type)
            yield payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session_ids(self) -> set[str]:
        """Query all session IDs belonging to this mission.

        Uses a short-lived session so long-running SSE streams do not hold a
        pool connection for their entire lifetime (only while this query runs).
        """
        async with get_async_session() as db:
            result = await db.execute(
                select(Session.id).where(Session.mission_id == self._mission_id)
            )
            return {row[0] for row in result.all()}

    async def _refresh_sessions(self) -> None:
        """Subscribe to any new sessions that appeared since last check."""
        current_ids = await self._get_session_ids()
        new_ids = current_ids - self._subscribed_ids
        for sid in new_ids:
            await self._subscribe_session(sid)
        if new_ids:
            logger.debug(
                "Console subscribed to new sessions",
                extra={
                    "mission_id": self._mission_id,
                    "new_session_count": len(new_ids),
                    "total_sessions": len(self._subscribed_ids),
                },
            )

    async def _subscribe_session(self, session_id: str) -> None:
        """Subscribe to a single session's Pub/Sub channel."""
        channel = f"{self._prefix}:{session_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        self._pubsubs.append(pubsub)
        self._subscribed_ids.add(session_id)

        task = asyncio.create_task(
            self._read_pubsub(pubsub, channel),
            name=f"console-sub-{session_id[:8]}",
        )
        self._tasks.append(task)

    async def _read_pubsub(self, pubsub, channel: str) -> None:
        """Read messages from a single Pub/Sub subscription and enqueue them."""
        try:
            while not self._stopped:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    await asyncio.sleep(0.01)
                    continue
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Invalid JSON in console event",
                        extra={"channel": channel},
                    )
                    continue

                event = deserialize_event(data)
                if event is not None:
                    await self._queue.put(event)
        except asyncio.CancelledError:
            pass

    async def _refresh_loop(self) -> None:
        """Periodically re-query sessions to pick up new ones."""
        try:
            while not self._stopped:
                await asyncio.sleep(self._refresh_interval)
                try:
                    await self._refresh_sessions()
                except Exception:
                    logger.warning(
                        "Console session refresh failed",
                        extra={"mission_id": self._mission_id},
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            pass
