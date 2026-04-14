"""
Mission Console Helpers.

Event classification and SSE formatting for the mission console.
Classifies events into categories (execution, chat, system) and
formats them for the frontend SSE wire protocol.
"""

import asyncio
import json
import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.events.types import SessionEvent
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

    # 4. Fetch persisted mission events that aren't already covered by
    #    session messages (chat) or execution records (runs/tasks).
    #    Only include event types unique to mission_events: system.info,
    #    mission.narrative, mission.artifact.found, and plan step events.
    from sqlalchemy import text

    _mission_event_types = (
        "system.info",
        "mission.narrative",
        "mission.artifact.found",
        "plan.step.started",
        "plan.step.completed",
        "system.execution.created",
        "system.execution.completed",
    )
    me_result = await db_session.execute(
        text(
            """SELECT id, event_type, source, created_at, data
               FROM mission_events
               WHERE mission_id = :mid
                 AND event_type = ANY(:types)
               ORDER BY created_at DESC
               LIMIT :lim"""
        ),
        {"mid": mission_id, "types": list(_mission_event_types), "lim": limit},
    )
    for row in me_result.fetchall():
        event_data = json.loads(row[4]) if isinstance(row[4], str) else (row[4] or {})
        timeline.append({
            "event_id": str(row[0]),
            "event_type": row[1],
            "category": classify_event(row[1]),
            "timestamp": row[3].isoformat() if row[3] else None,
            "source": row[2] or "",
            "data": event_data,
        })

    # 5. Sort unified timeline by timestamp descending, then truncate
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


def format_event_for_sse(event: SessionEvent) -> dict:
    """Wrap a SessionEvent into the SSE wire format the frontend expects.

    The history endpoint (``GET /missions/:id/console/history``) already
    returns events in a wrapped shape where the event envelope lives at
    the top level and everything else is nested under ``data``::

        {
            "event_id": "...",
            "event_type": "...",
            "category": "execution|chat|system",
            "timestamp": "...",
            "source": "...",
            "data": {...}  # all type-specific payload fields
        }

    But the SSE endpoints used to yield ``event.model_dump_json()``
    directly — a *flat* object with every Pydantic field (including
    ``mission_id``, ``task_id``, ``from_status``) at the top level and
    **no** ``data`` wrapper. That shape mismatch meant every SSE consumer
    that reached for ``event.data.something`` hit ``undefined`` and
    silently lost the event (or surfaced the error via whichever catch
    site happened to run next — typically a mutation toast). The
    symptom was exotic ("Cannot read properties of undefined (reading
    'agent_id')" when rejecting a plan task) but the cause was that
    literally every SSE event was getting dropped.

    This helper produces the wrapped shape so SSE and history share a
    single wire format. Callers should use this instead of
    ``event.model_dump_json()`` when writing to an ``EventSource``
    stream.
    """
    flat = json.loads(event.model_dump_json())
    event_type = flat.pop("event_type", "")
    return {
        "event_id": flat.pop("event_id", str(uuid.uuid4())),
        "event_type": event_type,
        "category": classify_event(event_type),
        "timestamp": flat.pop("timestamp", None),
        "source": flat.pop("source", ""),
        "data": flat,
    }


