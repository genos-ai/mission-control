"""Run memory service (Plan 88, 88.3.5).

Builds the run context packet: the previous run's digest and the Mission
Context Document (MCD) changes between the previous and the current run's
start watermarks (``context_version_start``). The packet feeds the
ContextAssembler per task and, rendered as markdown, the planning prompt
of an objective run. Learnings are selected per task inside the
ContextAssembler; prior outputs stay in ``load_prior_outputs``.

Never imports modules.backend.agents (import-linter contract).
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.utils import estimate_tokens
from modules.backend.models.mission_context import ChangeType, ContextChange
from modules.backend.models.mission_run import MissionRun, MissionRunStatus
from modules.backend.models.mission_run_digest import DigestGenerator, MissionRunDigest
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.mission_run_digest import MissionRunDigestRepository
from modules.backend.schemas.run_memory import (
    ContextDelta,
    ContextDeltaEntry,
    PreviousRunDigest,
    RunContextPacket,
)
from modules.backend.services.base import BaseService
from modules.backend.services.mission_context import MissionContextManager

_VALUELESS_CHANGE_TYPES = frozenset({ChangeType.REMOVE, ChangeType.ARCHIVE})


class RunMemoryService(BaseService):
    """Reads what earlier runs left behind for the current run."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._runs = MissionRunRepository(session)
        self._digests = MissionRunDigestRepository(session)
        self._context = MissionContextManager(session)

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
