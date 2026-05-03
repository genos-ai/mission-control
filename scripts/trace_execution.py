#!/usr/bin/env python3
"""
Execution Trace — reconstruct the full timeline for a mission run.

Correlates Director tool calls, plan task states, Temporal workflow
activities, SSE events, DB writes, and agent responses into a single
chronological trace.  For troubleshooting "why did this fail" and
"what did the Director see".

Usage:
    python scripts/trace_execution.py --mission ai-research --last
    python scripts/trace_execution.py --execution 019dec4d
    python scripts/trace_execution.py --workflow mission-run-019dcac7-30e
    python scripts/trace_execution.py --mission ai-research --last --filter errors,transitions
    python scripts/trace_execution.py --mission ai-research --last --json
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import cast, select, and_, String as SAString
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.backend.core.config import get_app_config
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger, setup_logging
from modules.backend.models.execution_record import (
    ExecutionDecision,
    ExecutionRecord,
    TaskAttempt,
    TaskExecution,
)
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission import Mission
from modules.backend.models.mission_event import MissionEvent
from modules.backend.models.mission_plan import MissionPlan, PlanTaskState
from modules.backend.models.session import Session, SessionMessage
from modules.backend.models.session_followup import SessionFollowup

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

COLORS = {
    "DIRECTOR": "blue",
    "PLAN": "cyan",
    "TEMPORAL": "magenta",
    "DISPATCH": "yellow",
    "SSE": "white",
    "DB": "green",
    "VALIDATE": "red",
    "FOLLOWUP": "bright_cyan",
    "LLM": "bright_magenta",
    "LOG": "white",
}

ERROR_KEYWORDS = {"failed", "error", "abort", "timeout", "exceeded", "exception"}


def _ts(dt: datetime | None) -> str:
    """Format a datetime as HH:MM:SS.mmm."""
    if dt is None:
        return "??:??:??.???"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _short_id(uid: str | None) -> str:
    """Truncate a UUID to its first 8 chars."""
    if uid is None:
        return "None"
    return str(uid)[:8]


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


async def resolve_mission_id(db: AsyncSession, name: str) -> str | None:
    stmt = select(Mission.id).where(Mission.name == name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def resolve_execution(
    db: AsyncSession,
    *,
    execution_id: str | None = None,
    mission_id: str | None = None,
    workflow_id: str | None = None,
    last: bool = False,
) -> ExecutionRecord | None:
    """Find the target ExecutionRecord from one of the lookup keys."""
    if execution_id:
        # Prefix match (cast UUID to text for LIKE)
        stmt = (
            select(ExecutionRecord)
            .where(cast(ExecutionRecord.id, SAString).like(f"{execution_id}%"))
            .order_by(ExecutionRecord.created_at.desc())
            .limit(1)
        )
    elif workflow_id:
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.temporal_workflow_id == workflow_id)
            .limit(1)
        )
    elif mission_id and last:
        stmt = (
            select(ExecutionRecord)
            .where(ExecutionRecord.mission_id == mission_id)
            .order_by(ExecutionRecord.created_at.desc())
            .limit(1)
        )
    else:
        return None

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def collect_execution_details(
    db: AsyncSession, record: ExecutionRecord
) -> dict:
    """Load task executions, attempts, and decisions for an execution."""
    stmt = (
        select(TaskExecution)
        .where(TaskExecution.execution_record_id == record.id)
        .options(selectinload(TaskExecution.attempts))
        .order_by(TaskExecution.started_at.asc().nullslast())
    )
    result = await db.execute(stmt)
    task_execs = list(result.scalars().all())

    stmt = (
        select(ExecutionDecision)
        .where(ExecutionDecision.execution_record_id == record.id)
        .order_by(ExecutionDecision.created_at.asc())
    )
    result = await db.execute(stmt)
    decisions = list(result.scalars().all())

    return {"task_executions": task_execs, "decisions": decisions}


async def collect_plan_states(
    db: AsyncSession, mission_plan_id: str
) -> list[PlanTaskState]:
    stmt = (
        select(PlanTaskState)
        .where(PlanTaskState.mission_plan_id == mission_plan_id)
        .order_by(PlanTaskState.updated_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def collect_mission_events(
    db: AsyncSession, mission_id: str, since: datetime | None = None
) -> list[MissionEvent]:
    conditions = [MissionEvent.mission_id == mission_id]
    if since:
        conditions.append(MissionEvent.timestamp >= since)
    stmt = (
        select(MissionEvent)
        .where(and_(*conditions))
        .order_by(MissionEvent.timestamp.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def collect_session_messages(
    db: AsyncSession, session_id: str, since: datetime | None = None
) -> list[SessionMessage]:
    conditions = [SessionMessage.session_id == session_id]
    if since:
        conditions.append(SessionMessage.created_at >= since)
    stmt = (
        select(SessionMessage)
        .where(and_(*conditions))
        .order_by(SessionMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def collect_followups(
    db: AsyncSession, session_id: str
) -> list[SessionFollowup]:
    stmt = (
        select(SessionFollowup)
        .where(SessionFollowup.session_id == session_id)
        .order_by(SessionFollowup.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def collect_llm_calls(
    db: AsyncSession,
    *,
    mission_id: str | None = None,
    execution_record_id: str | None = None,
    since: datetime | None = None,
) -> list[LlmCall]:
    conditions = []
    if execution_record_id:
        conditions.append(LlmCall.execution_record_id == execution_record_id)
    elif mission_id:
        conditions.append(LlmCall.mission_id == mission_id)
    else:
        return []
    if since:
        conditions.append(LlmCall.created_at >= since)
    stmt = (
        select(LlmCall)
        .where(and_(*conditions))
        .order_by(LlmCall.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def collect_mission_plan(
    db: AsyncSession, mission_id: str
) -> MissionPlan | None:
    stmt = select(MissionPlan).where(MissionPlan.mission_id == mission_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def collect_session_for_mission(
    db: AsyncSession, mission_id: str
) -> Session | None:
    stmt = (
        select(Session)
        .where(Session.mission_id == mission_id)
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Timeline event builders
# ---------------------------------------------------------------------------


class TraceEvent:
    """A single entry in the chronological trace."""

    __slots__ = ("timestamp", "source", "summary", "details", "is_error")

    def __init__(
        self,
        timestamp: datetime | None,
        source: str,
        summary: str,
        details: list[str] | None = None,
        is_error: bool = False,
    ):
        self.timestamp = timestamp or datetime.min.replace(tzinfo=timezone.utc)
        self.source = source
        self.summary = summary
        self.details = details or []
        self.is_error = is_error

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": self.source,
            "summary": self.summary,
            "details": self.details,
            "is_error": self.is_error,
        }


def build_execution_events(record: ExecutionRecord, details: dict) -> list[TraceEvent]:
    """Build trace events from an ExecutionRecord and its children."""
    events: list[TraceEvent] = []

    # Execution lifecycle
    events.append(TraceEvent(
        record.created_at, "DB",
        f"ExecutionRecord created  id={_short_id(record.id)}  status={record.status.name if hasattr(record.status, 'name') else record.status}",
        [
            f"mission_id={_short_id(record.mission_id)}",
            f"roster={record.roster_name}",
            f"temporal_workflow_id={record.temporal_workflow_id or 'None'}",
        ],
    ))

    if record.started_at:
        # Show the dispatched task plan snapshot
        dispatched_plan = record.task_plan_json or {}
        dispatched_tasks = dispatched_plan.get("tasks", [])
        task_summary = ", ".join(
            t.get("task_id", t.get("id", "?")) for t in dispatched_tasks[:10]
        ) if isinstance(dispatched_tasks, list) else "(no tasks)"
        events.append(TraceEvent(
            record.started_at, "DISPATCH",
            f"Execution started  id={_short_id(record.id)}  tasks_dispatched={len(dispatched_tasks) if isinstance(dispatched_tasks, list) else 0}",
            [
                f"objective={record.objective_statement or '(none)'}",
                f"dispatched_tasks=[{task_summary}]",
            ],
        ))

    # Task executions
    for te in details.get("task_executions", []):
        if te.started_at:
            events.append(TraceEvent(
                te.started_at, "DISPATCH",
                f"Task {te.task_id} started  agent={te.agent_name}",
            ))
        for attempt in getattr(te, "attempts", []):
            is_fail = str(getattr(attempt.status, "name", attempt.status)).upper() == "FAILED"
            events.append(TraceEvent(
                attempt.created_at, "DISPATCH",
                f"Task {te.task_id} attempt #{attempt.attempt_number}  status={attempt.status.name if hasattr(attempt.status, 'name') else attempt.status}",
                [
                    f"failure_tier={attempt.failure_tier}" if attempt.failure_tier else None,
                    f"failure_reason={attempt.failure_reason}" if attempt.failure_reason else None,
                ],
                is_error=is_fail,
            ))
        if te.completed_at:
            te_status = te.status.name if hasattr(te.status, "name") else te.status
            events.append(TraceEvent(
                te.completed_at, "DISPATCH",
                f"Task {te.task_id} completed  status={te_status}  cost=${te.cost_usd or 0:.4f}  duration={te.duration_seconds or 0:.1f}s",
                is_error=str(te_status).upper() == "FAILED",
            ))

    # Decisions
    for d in details.get("decisions", []):
        d_type = d.decision_type.name if hasattr(d.decision_type, "name") else d.decision_type
        events.append(TraceEvent(
            d.created_at, "DISPATCH",
            f"Decision: {d_type}" + (f"  task={d.task_id}" if d.task_id else ""),
            [f"reasoning={d.reasoning}"] if d.reasoning else [],
            is_error=d_type.upper() in {"FAIL", "ESCALATE"},
        ))

    # Completed
    if record.completed_at:
        status = record.status.name if hasattr(record.status, "name") else record.status
        events.append(TraceEvent(
            record.completed_at, "DB",
            f"ExecutionRecord completed  status={status}  cost=${record.total_cost_usd or 0:.4f}",
            [
                f"completed_tasks={record.completed_task_count or 0}  failed_tasks={record.failed_task_count or 0}",
            ],
            is_error=str(status).upper() in {"FAILED", "TIMED_OUT"},
        ))

    # Outcome
    outcome = record.execution_outcome_json
    if isinstance(outcome, dict):
        abort = outcome.get("abort_reason")
        if abort:
            events.append(TraceEvent(
                record.completed_at, "VALIDATE",
                f"Abort reason: {abort}",
                is_error=True,
            ))

    return events


def build_plan_metadata_events(plan: MissionPlan) -> list[TraceEvent]:
    """Emit a summary event for the MissionPlan itself."""
    events: list[TraceEvent] = []
    plan_status = plan.status.name if hasattr(plan.status, "name") else plan.status

    # Plan creation / current state
    task_plan = plan.task_plan_json or {}
    tasks = task_plan.get("tasks", [])
    task_ids = [t.get("task_id", t.get("id", "?")) for t in tasks] if isinstance(tasks, list) else []

    events.append(TraceEvent(
        plan.created_at, "PLAN",
        f"MissionPlan  id={_short_id(plan.id)}  v{plan.version}  status={plan_status}  gate_mode={plan.gate_mode}",
        [
            f"budget_ceiling=${plan.budget_usd_ceiling or 0:.2f}  spent=${plan.total_spent_usd or 0:.4f}",
            f"tasks ({len(tasks)}): {', '.join(task_ids[:10])}" + ("..." if len(task_ids) > 10 else ""),
            f"supervisor_iterations={plan.supervisor_iteration_count}/{plan.max_supervisor_iterations}",
        ],
    ))

    # Emit per-task definitions from the plan body
    for t in tasks if isinstance(tasks, list) else []:
        tid = t.get("task_id", t.get("id", "?"))
        agent = t.get("agent", t.get("agent_name", "?"))
        objective = t.get("objective", t.get("description", ""))[:150]
        deps = t.get("depends_on", t.get("upstream_task_ids", []))
        events.append(TraceEvent(
            plan.created_at, "PLAN",
            f"Task definition: {tid}  agent={agent}",
            [
                f"objective={objective}" if objective else None,
                f"depends_on={deps}" if deps else None,
            ],
        ))

    return events


def build_plan_state_events(states: list[PlanTaskState]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for s in states:
        status = s.status.name if hasattr(s.status, "name") else s.status
        detail_lines = []
        if s.failure_reason:
            detail_lines.append(f"failure_reason={s.failure_reason}")
        if s.result_summary:
            detail_lines.append(f"result_summary={s.result_summary[:120]}")
        if s.execution_record_id:
            detail_lines.append(f"execution_record_id={_short_id(s.execution_record_id)}")
        if s.cost_usd:
            detail_lines.append(f"cost=${s.cost_usd:.4f}  duration={s.duration_seconds or 0:.1f}s")

        events.append(TraceEvent(
            s.updated_at, "PLAN",
            f"Task {s.task_id} → {status}",
            detail_lines,
            is_error=str(status).upper() == "FAILED",
        ))
    return events


def build_sse_events(mission_events: list[MissionEvent]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for me in mission_events:
        data = me.data or {}
        detail_lines = []
        for key in ("status", "run_status", "failure_reason", "abort_reason", "action", "reason"):
            if key in data:
                detail_lines.append(f"{key}={data[key]}")
        is_err = any(kw in me.event_type.lower() for kw in ("error", "fail"))
        is_err = is_err or any(
            kw in str(data.get("status", "")).lower() or kw in str(data.get("run_status", "")).lower()
            for kw in ("failed", "error")
        )
        events.append(TraceEvent(
            me.timestamp, "SSE",
            f"{me.event_type}" + (f"  source={me.source}" if me.source else ""),
            detail_lines,
            is_error=is_err,
        ))
    return events


def build_message_events(messages: list[SessionMessage]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for msg in messages:
        role = msg.role
        if role == "tool_call":
            events.append(TraceEvent(
                msg.created_at, "DIRECTOR",
                f"Tool call: {msg.tool_name or '?'}",
                [f"content={msg.content[:200]}"] if msg.content else [],
            ))
        elif role == "tool_result":
            snippet = (msg.content or "")[:200]
            events.append(TraceEvent(
                msg.created_at, "DIRECTOR",
                f"Tool result: {msg.tool_name or '?'}",
                [f"→ {snippet}"] if snippet else [],
            ))
        elif role == "assistant":
            snippet = (msg.content or "")[:300]
            events.append(TraceEvent(
                msg.created_at, "DIRECTOR",
                f"Response rendered",
                [f"→ {snippet}"],
            ))
        elif role == "user":
            snippet = (msg.content or "")[:200]
            events.append(TraceEvent(
                msg.created_at, "DIRECTOR",
                f"User message",
                [f"→ {snippet}"],
            ))
        elif role == "system":
            snippet = (msg.content or "")[:200]
            events.append(TraceEvent(
                msg.created_at, "DIRECTOR",
                f"System message",
                [f"→ {snippet}"],
            ))
    return events


def build_followup_events(followups: list[SessionFollowup]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for fu in followups:
        events.append(TraceEvent(
            fu.created_at, "FOLLOWUP",
            f"Followup registered  triggers={fu.trigger_event_types}",
            [
                f"created_by={fu.created_by_agent}",
                f"max_fires={fu.max_fires}  fire_count={fu.fire_count}",
                f"expires_at={fu.expires_at}",
            ],
        ))
        if fu.consumed_at:
            events.append(TraceEvent(
                fu.consumed_at, "FOLLOWUP",
                f"Followup consumed (fired)",
                [f"prompt_template={fu.prompt_template[:150]}"] if fu.prompt_template else [],
            ))
    return events


def build_llm_events(calls: list[LlmCall]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for c in calls:
        total_tokens = (c.input_tokens or 0) + (c.output_tokens or 0) + (c.cache_read_tokens or 0)
        events.append(TraceEvent(
            c.created_at, "LLM",
            f"LLM call  agent={c.agent_name}  model={c.model}  cost=${c.cost_usd or 0:.4f}",
            [
                f"tokens: in={c.input_tokens} out={c.output_tokens} cache_read={c.cache_read_tokens} total={total_tokens}",
                f"latency={c.latency_ms}ms" if c.latency_ms else None,
            ],
        ))
    return events


def build_log_events(
    log_path: Path,
    mission_id: str,
    since: datetime | None = None,
) -> list[TraceEvent]:
    """Parse structured logs for mission-scoped entries."""
    events: list[TraceEvent] = []
    if not log_path.exists():
        return events

    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                extra = entry.get("extra", {})
                if str(extra.get("mission_id", "")) != str(mission_id):
                    continue
                ts_str = entry.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if since and ts < since:
                    continue

                level = entry.get("level", "info").upper()
                is_err = level in ("ERROR", "CRITICAL", "WARNING")
                events.append(TraceEvent(
                    ts, "LOG",
                    f"[{level}] {entry.get('event', '')}",
                    [
                        f"logger={entry.get('logger', '')}",
                        f"extra={json.dumps({k: v for k, v in extra.items() if k != 'mission_id'})}" if extra else None,
                    ],
                    is_error=is_err,
                ))
    except OSError:
        pass

    return events


# ---------------------------------------------------------------------------
# Temporal workflow history (optional)
# ---------------------------------------------------------------------------


async def collect_temporal_events(workflow_id: str) -> list[TraceEvent]:
    """Fetch Temporal workflow history. Returns empty list if unavailable."""
    events: list[TraceEvent] = []
    try:
        from modules.backend.temporal.client import get_temporal_client
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()

        for event in history.events:
            ts = event.event_time.ToDatetime().replace(tzinfo=timezone.utc) if event.event_time else None
            etype = str(event.event_type)
            detail_lines = []

            # Extract activity info if available
            if hasattr(event, "activity_task_scheduled_event_attributes"):
                attrs = event.activity_task_scheduled_event_attributes
                if attrs and hasattr(attrs, "activity_type"):
                    detail_lines.append(f"activity={attrs.activity_type.name}")
            if hasattr(event, "activity_task_completed_event_attributes"):
                detail_lines.append("activity completed")
            if hasattr(event, "activity_task_failed_event_attributes"):
                attrs = event.activity_task_failed_event_attributes
                if attrs and hasattr(attrs, "failure"):
                    detail_lines.append(f"failure={attrs.failure.message[:200]}")

            is_err = "FAILED" in etype or "TIMED_OUT" in etype
            events.append(TraceEvent(
                ts, "TEMPORAL",
                etype.replace("EVENT_TYPE_", ""),
                detail_lines,
                is_error=is_err,
            ))
    except Exception as e:
        events.append(TraceEvent(
            datetime.now(timezone.utc), "TEMPORAL",
            f"(Temporal unavailable: {e})",
            is_error=False,
        ))
    return events


# ---------------------------------------------------------------------------
# Diagnosis engine
# ---------------------------------------------------------------------------


def diagnose(
    timeline: list[TraceEvent],
    record: ExecutionRecord,
    plan_states: list[PlanTaskState],
) -> list[str]:
    """Identify common failure patterns from the timeline."""
    findings: list[str] = []
    status = record.status.name if hasattr(record.status, "name") else str(record.status)

    # 1. Budget validation failure
    outcome = record.execution_outcome_json or {}
    abort = outcome.get("abort_reason", "")
    if "budget" in abort.lower():
        findings.append("Budget validation failed — estimated cost exceeded mission budget.")

    # 2. Zero tasks executed despite having a plan
    task_results = outcome.get("task_results", [])
    if status.upper() == "FAILED" and len(task_results) == 0:
        findings.append(
            "Execution FAILED with zero task results — plan may have failed validation "
            "before any agent was dispatched."
        )

    # 3. Tasks stuck in APPROVED/RUNNING
    for s in plan_states:
        ps = s.status.name if hasattr(s.status, "name") else str(s.status)
        if ps.upper() in ("APPROVED", "RUNNING") and status.upper() in ("FAILED", "COMPLETED"):
            findings.append(
                f"Task {s.task_id} still in {ps} after execution finished — "
                f"possible stale state (dispatch failed before marking task)."
            )

    # 4. Director did not detect failure (followup fired but no get_plan call after)
    followup_fired = False
    director_checked = False
    for ev in timeline:
        if ev.source == "FOLLOWUP" and "consumed" in ev.summary.lower():
            followup_fired = True
        if followup_fired and ev.source == "DIRECTOR" and "get_plan" in ev.summary.lower():
            director_checked = True

    if followup_fired and not director_checked and status.upper() == "FAILED":
        findings.append(
            "Director followup fired but Director did not call get_plan to check task states — "
            "may not have detected the failure."
        )

    # 5. General error count
    error_count = sum(1 for ev in timeline if ev.is_error)
    if error_count > 0:
        findings.append(f"Total error events in trace: {error_count}")

    return findings


# ---------------------------------------------------------------------------
# Filter logic
# ---------------------------------------------------------------------------


def apply_filters(timeline: list[TraceEvent], filters: set[str]) -> list[TraceEvent]:
    """Apply user-specified filters."""
    if not filters:
        return timeline

    filtered = []
    for ev in timeline:
        if "errors" in filters and ev.is_error:
            filtered.append(ev)
            continue
        if "transitions" in filters and ev.source == "PLAN":
            filtered.append(ev)
            continue
        if "director" in filters and ev.source == "DIRECTOR":
            filtered.append(ev)
            continue
        if "temporal" in filters and ev.source == "TEMPORAL":
            filtered.append(ev)
            continue
        if "llm" in filters and ev.source == "LLM":
            filtered.append(ev)
            continue
        if "sse" in filters and ev.source == "SSE":
            filtered.append(ev)
            continue
        if "followup" in filters and ev.source == "FOLLOWUP":
            filtered.append(ev)
            continue
        if "dispatch" in filters and ev.source == "DISPATCH":
            filtered.append(ev)
            continue
        if "log" in filters and ev.source == "LOG":
            filtered.append(ev)
            continue
    return filtered


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_text(
    timeline: list[TraceEvent],
    record: ExecutionRecord,
    mission_name: str,
    diagnosis: list[str],
):
    """Render the trace to stdout with color coding."""
    status = record.status.name if hasattr(record.status, "name") else str(record.status)
    header = f"EXECUTION TRACE: {mission_name} / {_short_id(record.id)}"
    click.echo()
    click.secho(header, bold=True)
    click.secho("=" * max(60, len(header)), bold=True)
    click.echo()

    for ev in timeline:
        color = COLORS.get(ev.source, "white")
        ts_str = _ts(ev.timestamp)
        source_pad = f"{ev.source:<12}"

        if ev.is_error:
            click.secho(f"{ts_str}  {source_pad}{ev.summary}", fg="red", bold=True)
        else:
            click.echo(
                click.style(f"{ts_str}  ", dim=True)
                + click.style(source_pad, fg=color)
                + ev.summary
            )

        for line in ev.details:
            if line:
                click.echo(click.style(f"{'':>26}{line}", dim=True))

    # Diagnosis
    if diagnosis:
        click.echo()
        click.secho("=" * 60, bold=True)
        click.secho(f"DIAGNOSIS ({status})", fg="red" if "FAIL" in status.upper() else "green", bold=True)
        click.echo()
        for finding in diagnosis:
            click.echo(f"  - {finding}")

    click.echo()


def render_json(
    timeline: list[TraceEvent],
    record: ExecutionRecord,
    mission_name: str,
    diagnosis: list[str],
):
    """Render the trace as JSON to stdout."""
    status = record.status.name if hasattr(record.status, "name") else str(record.status)
    output = {
        "mission": mission_name,
        "execution_id": str(record.id),
        "status": status,
        "total_cost_usd": float(record.total_cost_usd or 0),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "temporal_workflow_id": record.temporal_workflow_id,
        "event_count": len(timeline),
        "error_count": sum(1 for e in timeline if e.is_error),
        "timeline": [ev.to_dict() for ev in timeline],
        "diagnosis": diagnosis,
    }
    click.echo(json.dumps(output, indent=2, default=str))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_trace(
    *,
    mission_name: str | None,
    execution_id: str | None,
    workflow_id: str | None,
    last: bool,
    filters: set[str],
    output_json: bool,
    since_hours: float | None,
):
    async with get_async_session() as db:
        # Resolve mission
        mission_id = None
        resolved_name = mission_name or "(unknown)"
        if mission_name:
            mission_id = await resolve_mission_id(db, mission_name)
            if not mission_id:
                click.secho(f"Mission '{mission_name}' not found.", fg="red")
                sys.exit(1)

        # Resolve execution
        record = await resolve_execution(
            db,
            execution_id=execution_id,
            mission_id=mission_id,
            workflow_id=workflow_id,
            last=last,
        )
        if not record:
            click.secho("No execution record found for the given criteria.", fg="red")
            sys.exit(1)

        # If we didn't have a mission name, resolve it
        if not mission_name and record.mission_id:
            mission_id = record.mission_id
            stmt = select(Mission.name).where(Mission.id == record.mission_id)
            result = await db.execute(stmt)
            resolved_name = result.scalar_one_or_none() or "(unknown)"

        since = None
        if since_hours:
            since = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            from datetime import timedelta
            since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

        # Collect from all sources
        exec_details = await collect_execution_details(db, record)
        timeline: list[TraceEvent] = build_execution_events(record, exec_details)

        # Mission plan states
        plan = await collect_mission_plan(db, mission_id) if mission_id else None
        plan_states: list[PlanTaskState] = []
        if plan:
            timeline.extend(build_plan_metadata_events(plan))
            plan_states = await collect_plan_states(db, plan.id)
            timeline.extend(build_plan_state_events(plan_states))

        # Mission events (SSE)
        if mission_id:
            mission_events = await collect_mission_events(db, mission_id, since=since)
            timeline.extend(build_sse_events(mission_events))

        # Session messages (Director)
        session = await collect_session_for_mission(db, mission_id) if mission_id else None
        if session:
            messages = await collect_session_messages(db, session.id, since=since)
            timeline.extend(build_message_events(messages))
            followups = await collect_followups(db, session.id)
            timeline.extend(build_followup_events(followups))

        # LLM calls
        if mission_id:
            llm_calls = await collect_llm_calls(
                db, mission_id=mission_id, execution_record_id=str(record.id), since=since
            )
            timeline.extend(build_llm_events(llm_calls))

        # Structured logs
        log_path = PROJECT_ROOT / "var" / "logs" / "system.jsonl"
        if mission_id:
            timeline.extend(build_log_events(log_path, str(mission_id), since=since))

        # Temporal workflow history (optional, async)
        if record.temporal_workflow_id:
            temporal_events = await collect_temporal_events(record.temporal_workflow_id)
            timeline.extend(temporal_events)

        # Sort by timestamp
        timeline.sort(key=lambda e: e.timestamp)

        # Filter
        if filters:
            timeline = apply_filters(timeline, filters)

        # Diagnose
        findings = diagnose(timeline, record, plan_states)

        # Render
        if output_json:
            render_json(timeline, record, resolved_name, findings)
        else:
            render_text(timeline, record, resolved_name, findings)


@click.command()
@click.option("--mission", "-m", "mission_name", help="Mission name (e.g. ai-research)")
@click.option("--execution", "-e", "execution_id", help="Execution record ID (prefix match)")
@click.option("--workflow", "-w", "workflow_id", help="Temporal workflow ID")
@click.option("--last", is_flag=True, help="Use the most recent execution for the mission")
@click.option("--filter", "-f", "filter_str", help="Comma-separated filters: errors,transitions,director,temporal,llm,sse,followup,dispatch,log")
@click.option("--json", "output_json", is_flag=True, help="JSON output for piping")
@click.option("--since", "since_hours", type=float, help="Only include events from the last N hours")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
def main(
    mission_name: str | None,
    execution_id: str | None,
    workflow_id: str | None,
    last: bool,
    filter_str: str | None,
    output_json: bool,
    since_hours: float | None,
    verbose: bool,
):
    """Reconstruct the full execution timeline for a mission run."""
    setup_logging(level="DEBUG" if verbose else "WARNING", format_type="console")

    if not any([mission_name, execution_id, workflow_id]):
        click.secho("Provide at least one of: --mission, --execution, --workflow", fg="red")
        sys.exit(1)

    if mission_name and not (last or execution_id):
        click.secho("When using --mission, also pass --last or --execution", fg="red")
        sys.exit(1)

    filters = set()
    if filter_str:
        filters = {f.strip().lower() for f in filter_str.split(",")}

    asyncio.run(run_trace(
        mission_name=mission_name,
        execution_id=execution_id,
        workflow_id=workflow_id,
        last=last,
        filters=filters,
        output_json=output_json,
        since_hours=since_hours,
    ))


if __name__ == "__main__":
    main()
