"""Run memory service (Plan 88, 88.3.5, 88.3.7).

Builds the run context packet: the previous run's digest and the Mission
Context Document (MCD) changes between the previous and the current run's
start watermarks (``context_version_start``). The packet feeds the
ContextAssembler per task and, rendered as markdown, the planning prompt
of an objective run. Learnings are selected per task inside the
ContextAssembler; prior outputs stay in ``load_prior_outputs``.

Writes the run's end-of-run digest (88.3.7): a deterministic draft, with the
digest agent's narrative merged in when a narrator is passed. The agent is
injected as a DigestNarrator, so this module never imports
modules.backend.agents (import-linter contract).
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import (
    ExternalServiceError,
    MissionRunStateError,
    NotFoundError,
)
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.core.utils import estimate_tokens, utc_now
from modules.backend.events.base import SessionEvent
from modules.backend.events.mission_run_types import MissionRunDigestWrittenEvent
from modules.backend.events.types import SystemEvent
from modules.backend.models.mission_context import ChangeType, ContextChange
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunStatusReason
from modules.backend.models.mission_run_digest import DigestGenerator, MissionRunDigest
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.llm_ledger import LlmLedgerRepository
from modules.backend.repositories.mission_artifact import MissionArtifactRepository
from modules.backend.repositories.mission_context import MissionContextRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.mission_run_digest import MissionRunDigestRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.run_memory import (
    ContextDelta,
    ContextDeltaEntry,
    DigestContextChange,
    DigestDraft,
    DigestMetrics,
    DigestNarrative,
    DigestNarrator,
    DigestOpenItemOut,
    DigestOutcome,
    PreviousRunDigest,
    RunContextPacket,
)
from modules.backend.services.base import BaseService
from modules.backend.services.mission_context import MissionContextManager

_VALUELESS_CHANGE_TYPES = frozenset({ChangeType.REMOVE, ChangeType.ARCHIVE})
# A digest is written at run end, before the run leaves one of these (contract 3.2.1).
_DIGESTIBLE_STATUSES = frozenset(
    {MissionRunStatus.RUNNING, MissionRunStatus.AWAITING_GATE, MissionRunStatus.PAUSED}
)
_UNEXECUTED_TASK_STATUSES = frozenset({TaskStatus.PROPOSED, TaskStatus.APPROVED})
_DIGEST_SCHEMA_VERSION = 1
_SOURCE = "run_memory"


class RunMemoryService(BaseService):
    """Reads what earlier runs left behind for the current run and writes the run's digest."""

    def __init__(self, session: AsyncSession, *, event_bus: EventBusProtocol | None = None) -> None:
        super().__init__(session)
        self._event_bus = event_bus
        self._runs = MissionRunRepository(session)
        self._digests = MissionRunDigestRepository(session)
        self._context = MissionContextManager(session)
        self._context_repo = MissionContextRepository(session)
        self._tasks = TaskRepository(session)
        self._artifacts = MissionArtifactRepository(session)
        self._ledger = LlmLedgerRepository(session)

    async def build_context_packet(self, run_id: str) -> RunContextPacket:
        """The run's packet; a first run (no comparable previous run) has neither layer."""
        run = await self._runs.get_by_id(run_id)
        prev = (
            await self._runs.get_by_id_or_none(run.previous_run_id)
            if run.previous_run_id is not None
            else None
        )
        if prev is None or prev.context_version_start is None or run.context_version_start is None:
            return RunContextPacket(
                mission_run_id=run_id,
                is_first_run=True,
                previous_run_digest=None,
                context_delta=None,
            )
        digest = await self._digests.get_by_run(prev.id)
        return RunContextPacket(
            mission_run_id=run_id,
            is_first_run=False,
            previous_run_digest=self._previous_digest(prev, digest) if digest else None,
            context_delta=await self._context_delta(run, prev),
        )

    def render_planning_brief(self, packet: RunContextPacket) -> str:
        """Deterministic markdown of the packet for the planning prompt; "" on a first run."""
        if packet.is_first_run:
            return ""
        sections: list[str] = []
        digest = packet.previous_run_digest
        if digest is not None:
            lines = [
                f"## Previous run (#{digest.sequence}, {digest.status}, "
                f"digest: {digest.generator})",
                digest.summary,
            ]
            if digest.open_items:
                lines.append("### Open items")
                lines.extend(f"- {item.get('text', '')}" for item in digest.open_items)
            sections.append("\n".join(lines))
        delta = packet.context_delta
        if delta is not None and (delta.entries or delta.omitted_count > 0):
            lines = [
                "## Mission context changes since previous run "
                f"(v{delta.from_version}→v{delta.to_version})"
            ]
            lines.extend(f"- v{e.version} {e.change_type} {e.path}" for e in delta.entries)
            if delta.omitted_count > 0:
                lines.append(f"({delta.omitted_count} older changes omitted)")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    @staticmethod
    def _previous_digest(prev: MissionRun, digest: MissionRunDigest) -> PreviousRunDigest:
        """The previous run's digest with its summary truncated."""
        max_chars = get_app_config().missions.context_packet.previous_digest_max_chars
        return PreviousRunDigest(
            mission_run_id=prev.id,
            sequence=prev.sequence,
            status=MissionRunStatus(prev.status).value,
            generator=DigestGenerator(digest.generator).value,
            summary=digest.summary[:max_chars],
            open_items=list(digest.open_items or []),
            metrics=dict(digest.metrics or {}),
        )

    async def _context_delta(self, run: MissionRun, prev: MissionRun) -> ContextDelta:
        """MCD changes in (prev.context_version_start, run.context_version_start], token-bounded.

        The newest ``context_delta_max_changes`` changes are read; the oldest
        are dropped until the delta fits ``context_delta_max_tokens``.
        ``omitted_count`` counts every change in the window not shown.
        """
        cfg = get_app_config().missions.context_packet
        after, up_to = prev.context_version_start, run.context_version_start
        changes = await self._context.get_changes_between(
            run.mission_id, after, up_to, limit=cfg.context_delta_max_changes
        )
        entries = [
            self._delta_entry(c, cfg.context_delta_value_max_chars) for c in reversed(changes)
        ]
        delta = ContextDelta(from_version=after, to_version=up_to, entries=entries, omitted_count=0)
        while delta.entries and (
            estimate_tokens(delta.model_dump(mode="json")) > cfg.context_delta_max_tokens
        ):
            delta.entries.pop(0)
        total = await self._context.count_changes_between(run.mission_id, after, up_to)
        delta.omitted_count = total - len(delta.entries)
        return delta

    @staticmethod
    def _delta_entry(change: ContextChange, max_chars: int) -> ContextDeltaEntry:
        """One rendered change: JSON value excerpt (None for REMOVE/ARCHIVE), reason truncated."""
        change_type = ChangeType(change.change_type)
        excerpt = (
            None
            if change_type in _VALUELESS_CHANGE_TYPES
            else json.dumps(change.new_value, ensure_ascii=False)[:max_chars]
        )
        return ContextDeltaEntry(
            version=change.version,
            change_type=change_type.value,
            path=change.path,
            value_excerpt=excerpt,
            reason=change.reason[:max_chars],
        )

    # ── Digest (88.3.7) ──────────────────────────────────────────────────

    async def get_digest(self, mission_id: str, run_id: str) -> MissionRunDigest | None:
        """The run's digest, None when the run has none or belongs to another mission."""
        return await self._digests.get_for_mission(mission_id, run_id)

    async def write_digest(
        self,
        run_id: str,
        *,
        status: MissionRunStatus,
        reason: MissionRunStatusReason | None,
        narrator: DigestNarrator | None,
    ) -> MissionRunDigest:
        """Write the run's digest once; a replay returns the stored row without an LLM call.

        Builds the deterministic draft, commits to end the read transaction,
        calls ``narrator`` (when given) with no row lock held, then locks the
        run, re-checks its status and inserts the digest with
        ``context_version_end``. A narrator ExternalServiceError degrades to
        the deterministic digest (contract 3.1.7). The end reason resolves through
        ``MissionRun.end_reason``, the rule finalise applies.

        Raises:
            MissionRunStateError: the run is not RUNNING, AWAITING_GATE or PAUSED.
        """
        existing = await self._digests.get_by_run(run_id)
        if existing is not None:
            return existing

        run = await self._runs.get_by_id(run_id)
        _require_digestible(run)
        reason = run.end_reason(status, reason)
        mission_id, session_id, objective = run.mission_id, run.session_id, run.objective
        end = await self._context_repo.get_version(mission_id)
        tasks = await self._tasks.list_by_run(run_id)
        draft = await self._build_draft(run, tasks, end, status=status, reason=reason)
        excerpts = _task_excerpts(tasks[: len(draft.outcomes)])
        await self._session.commit()

        generator, generation_cost = DigestGenerator.DETERMINISTIC, 0.0
        if narrator is not None:
            try:
                narrative, cost = await narrator(
                    draft=draft.model_dump(mode="json"),
                    objective=objective,
                    task_excerpts=excerpts,
                    mission_id=mission_id,
                    mission_run_id=run_id,
                    session_id=session_id,
                )
            except ExternalServiceError:
                # Degraded path of contract 3.1.7: spend already recorded stays in llm_calls.
                self._logger.warning(
                    "Digest agent failed; writing a deterministic digest",
                    extra={"mission_id": mission_id, "mission_run_id": run_id},
                    exc_info=True,
                )
                await self._emit(
                    mission_id,
                    SystemEvent(
                        session_id=uuid.UUID(session_id or mission_id),
                        source=_SOURCE,
                        level="warning",
                        message=f"Digest agent failed for run {run_id}; digest is deterministic",
                        mission_id=mission_id,
                    ),
                )
            else:
                draft = _merge_narrative(draft, narrative)
                generator, generation_cost = DigestGenerator.AGENT, cost

        digest = await self._insert_digest(
            run_id, mission_id, draft, end, generator=generator, generation_cost=generation_cost
        )
        await self._publish_digest_written(digest, session_id)
        return digest

    async def _build_draft(
        self,
        run: MissionRun,
        tasks: list[Task],
        end: int,
        *,
        status: MissionRunStatus,
        reason: MissionRunStatusReason | None,
    ) -> DigestDraft:
        """The deterministic digest; every list in tasks.created_at order."""
        cfg = get_app_config().missions
        artifact_ids = await self._artifacts.ids_by_task_for_run(run.id)
        cap = cfg.digest.headline_max_chars
        outcomes = [
            DigestOutcome(
                task_id=task.id,
                agent=task.agent,
                status=TaskStatus(task.status).value,
                headline=_headline(task)[:cap],
                artifact_ids=artifact_ids.get(task.id, []),
            )
            for task in tasks[: cfg.digest.max_outcomes]
        ]
        changes = await self._context.get_changes_between(
            run.mission_id,
            run.context_version_start,
            end,
            limit=cfg.context_packet.context_delta_max_changes,
        )
        completed = sum(1 for t in tasks if TaskStatus(t.status) == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if TaskStatus(t.status) == TaskStatus.FAILED)
        cost = await self._ledger.sum_cost(
            run.mission_id, since=None, until=None, mission_run_id=run.id
        )
        summary = (
            f"Run #{run.sequence} ended {status.value} ({reason.value if reason else 'none'}). "
            f"{completed}/{len(tasks)} tasks completed, {failed} failed. Spend ${cost:.2f}."
        )
        if run.objective:
            summary += f" Objective: {run.objective}"
        return DigestDraft(
            summary=summary[: cfg.digest.summary_max_chars],
            outcomes=outcomes,
            decisions=[],
            open_items=_open_items(tasks, cap),
            context_changes=[
                DigestContextChange(
                    version=c.version, change_type=ChangeType(c.change_type).value, path=c.path
                )
                for c in reversed(changes)
            ],
            metrics=DigestMetrics(
                cost_usd=cost,
                duration_seconds=(utc_now() - run.started_at).total_seconds(),
                task_count=len(tasks),
                completed_task_count=completed,
                failed_task_count=failed,
                iteration_count=run.iteration_count,
            ),
        )

    async def _insert_digest(
        self,
        run_id: str,
        mission_id: str,
        draft: DigestDraft,
        end: int,
        *,
        generator: DigestGenerator,
        generation_cost: float,
    ) -> MissionRunDigest:
        """Lock the run, re-check its status, insert the digest and set context_version_end."""
        run = await self._runs.lock_current(mission_id, run_id)
        if run is None:
            raise NotFoundError(f"Run {run_id} not found in mission {mission_id}")
        _require_digestible(run)
        cfg = get_app_config().missions.digest
        digest = await self._digests.insert_if_absent(
            mission_run_id=run_id,
            mission_id=mission_id,
            schema_version=_DIGEST_SCHEMA_VERSION,
            generator=generator,
            summary=draft.summary[: cfg.summary_max_chars],
            outcomes=[o.model_dump(mode="json") for o in draft.outcomes],
            decisions=list(draft.decisions),
            open_items=[i.model_dump(mode="json") for i in draft.open_items],
            context_changes=[c.model_dump(mode="json") for c in draft.context_changes],
            metrics=draft.metrics.model_dump(mode="json"),
            generation_cost_usd=generation_cost,
        )
        if digest is None:
            await self._session.commit()
            existing = await self._digests.get_by_run(run_id)
            if existing is None:
                raise NotFoundError(f"Digest of run {run_id} conflicted but is not readable")
            return existing
        run.context_version_end = end
        await self._session.commit()
        self._log_digest(digest)
        return digest

    def _log_digest(self, digest: MissionRunDigest) -> None:
        self._logger.info(
            "Run digest written",
            extra={
                "mission_id": digest.mission_id,
                "mission_run_id": digest.mission_run_id,
                "digest_id": digest.id,
                "generator": DigestGenerator(digest.generator).value,
            },
        )

    async def _publish_digest_written(
        self, digest: MissionRunDigest, session_id: str | None
    ) -> None:
        """Publish MissionRunDigestWrittenEvent once the digest is committed."""
        await self._emit(
            digest.mission_id,
            MissionRunDigestWrittenEvent(
                session_id=uuid.UUID(session_id or digest.mission_id),
                source=_SOURCE,
                mission_id=digest.mission_id,
                mission_run_id=digest.mission_run_id,
                digest_id=digest.id,
                generator=DigestGenerator(digest.generator).value,
            ),
        )

    async def _emit(self, mission_id: str, event: SessionEvent) -> None:
        """Publish when a bus is set; emission is best-effort and never fails the digest."""
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception as err:  # noqa: BLE001
            # best-effort — this IS the event-emission path; the digest row is the record.
            self._logger.warning(
                "Failed to publish run memory event",
                extra={"mission_id": mission_id, "event_type": event.event_type, "error": str(err)},
            )


def _require_digestible(run: MissionRun) -> None:
    """Raise unless the run is RUNNING, AWAITING_GATE or PAUSED and begin has stamped it."""
    status = MissionRunStatus(run.status)
    if (
        status not in _DIGESTIBLE_STATUSES
        or run.started_at is None
        or run.context_version_start is None
    ):
        raise MissionRunStateError(
            f"Run {run.id} is {status.value}; a digest needs a started, non-terminal run"
        )


def _headline(task: Task) -> str:
    """failure_reason for a FAILED task; else result_summary's summary, result or raw text."""
    if TaskStatus(task.status) == TaskStatus.FAILED:
        return task.failure_reason or ""
    raw = task.result_summary or ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(parsed, dict):
        for key in ("summary", "result"):
            value = parsed.get(key)
            if value:
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return raw


def _open_items(tasks: list[Task], max_chars: int) -> list[DigestOpenItemOut]:
    """One item per FAILED task and per task still PROPOSED or APPROVED."""
    items = []
    for task in tasks:
        status = TaskStatus(task.status)
        if status == TaskStatus.FAILED:
            text = f"{task.agent} failed: {task.failure_reason}"
        elif status in _UNEXECUTED_TASK_STATUSES:
            text = f"Not executed: {task.description}"
        else:
            continue
        items.append(DigestOpenItemOut(text=text[:max_chars], source_task_id=task.id))
    return items


def _task_excerpts(tasks: list[Task]) -> list[dict]:
    """Bounded per-task output the digest agent narrates from."""
    max_chars = get_app_config().missions.digest.task_excerpt_max_chars
    return [
        {
            "task_id": task.id,
            "agent": task.agent,
            "status": TaskStatus(task.status).value,
            "excerpt": (task.result_summary or task.failure_reason or "")[:max_chars],
        }
        for task in tasks
    ]


def _merge_narrative(draft: DigestDraft, narrative: DigestNarrative) -> DigestDraft:
    """Narrative summary; open items deduplicated on text; narrative headlines by task id."""
    max_chars = get_app_config().missions.digest.headline_max_chars
    seen: set[str] = set()
    open_items = []
    for item in [
        *draft.open_items,
        *(
            DigestOpenItemOut(text=i.text[:max_chars], source_task_id=i.source_task_id)
            for i in narrative.open_items
        ),
    ]:
        if item.text not in seen:
            seen.add(item.text)
            open_items.append(item)
    headlines = {h.task_id: h.headline[:max_chars] for h in narrative.headlines}
    outcomes = [
        o.model_copy(update={"headline": headlines[o.task_id]}) if o.task_id in headlines else o
        for o in draft.outcomes
    ]
    return draft.model_copy(
        update={"summary": narrative.summary, "outcomes": outcomes, "open_items": open_items}
    )
