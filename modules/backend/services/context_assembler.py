"""
Context Assembler.

Builds the context packet an agent receives before task execution
(Plan 88, 88.3.5).

Fixed head, never trimmed:
  project_context (MCD), task, inputs (summarised if over budget)

Optional layers, in missions.context_packet.assembly_order, each sized to
min(its own cap, remaining budget) and included whole only when it fits:
  previous_run_digest, context_delta (run-scoped, from RunMemoryService),
  code_map (coding tasks), learnings, history (tasks with domain_tags)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from modules.backend.core.config import get_app_config, get_mission_control_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import estimate_tokens
from modules.backend.repositories.mission_learning import MissionLearningRepository
from modules.backend.services.history_query import HistoryQueryService
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.run_memory import RunMemoryService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.schemas.run_memory import PreviousRunDigest, RunContextPacket
    from modules.backend.services.code_map.loader import CodeMapLoader

logger = get_logger(__name__)


# Domain tags that indicate a task needs codebase structural context
_CODING_TAGS = frozenset(
    {
        "code",
        "implementation",
        "refactor",
        "bugfix",
        "feature",
        "migration",
        "testing",
    }
)


class ContextAssembler:
    """Builds context packets for agents within the dispatch token budget."""

    def __init__(
        self,
        context_manager: MissionContextManager,
        history_service: HistoryQueryService,
        *,
        learning_repo: MissionLearningRepository,
        run_memory: RunMemoryService,
        code_map_loader: CodeMapLoader | None = None,
    ) -> None:
        self._context_manager = context_manager
        self._history_service = history_service
        self._learning_repo = learning_repo
        self._run_memory = run_memory
        self._code_map_loader = code_map_loader
        self._packets: dict[str, RunContextPacket] = {}

    @staticmethod
    def for_session(
        session: AsyncSession,
        *,
        context_manager: MissionContextManager,
        code_map_loader: CodeMapLoader | None,
    ) -> ContextAssembler:
        """A ContextAssembler whose dependencies all use ``session``.

        ``context_manager`` is passed in so a caller can share it with the
        ContextCurator. Callers outside the service layer use this instead
        of constructing repositories themselves.
        """
        return ContextAssembler(
            context_manager,
            HistoryQueryService(session),
            learning_repo=MissionLearningRepository(session),
            run_memory=RunMemoryService(session),
            code_map_loader=code_map_loader,
        )

    @staticmethod
    @asynccontextmanager
    async def factory(
        code_map_loader: CodeMapLoader | None,
    ) -> AsyncGenerator[ContextAssembler, None]:
        """A ContextAssembler with a DB session of its own (read-only)."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield ContextAssembler.for_session(
                db, context_manager=MissionContextManager(db), code_map_loader=code_map_loader
            )

    async def build(
        self,
        mission_id: str,
        task_definition: dict,
        resolved_inputs: dict,
        *,
        domain_tags: list[str] | None,
        mission_run_id: str | None,
    ) -> dict:
        """Fixed head plus the optional layers below, in assembly_order."""
        dispatch_cfg = get_mission_control_config().dispatch
        missions_cfg = get_app_config().missions
        packet_cfg = missions_cfg.context_packet
        learnings_cfg = missions_cfg.knowledge.learnings
        budget = dispatch_cfg.context_token_budget
        remaining = budget
        packet: dict[str, Any] = {}

        # Fixed head (never trimmed)
        pcd = await self._context_manager.get_context(mission_id)
        packet["project_context"] = pcd
        remaining -= estimate_tokens(pcd)
        packet["task"] = task_definition
        remaining -= estimate_tokens(task_definition)
        input_tokens = estimate_tokens(resolved_inputs)
        if input_tokens <= remaining:
            packet["inputs"] = resolved_inputs
            remaining -= input_tokens
        else:
            summarized = {
                k: (
                    f"<{type(v).__name__}, {len(str(v))} chars>"
                    if not isinstance(v, (str, int, float, bool))
                    else v
                )
                for k, v in resolved_inputs.items()
            }
            packet["inputs"] = summarized
            remaining -= estimate_tokens(summarized)

        caps: dict[str, int] = {
            "previous_run_digest": packet_cfg.previous_digest_max_chars // 4,
            "context_delta": packet_cfg.context_delta_max_tokens,
            "learnings": learnings_cfg.context_assembler_reserve_tokens,
            "history": dispatch_cfg.history_reserve_tokens,
        }
        order = packet_cfg.assembly_order
        for idx, layer in enumerate(order):
            if layer == "code_map":
                cap = remaining - sum(caps[later] for later in order[idx + 1 :])
            else:
                cap = caps[layer]
            limit = min(cap, remaining)
            if limit <= 0:
                continue
            value = await self._layer_value(
                layer,
                mission_id=mission_id,
                domain_tags=domain_tags,
                mission_run_id=mission_run_id,
                limit=limit,
                max_entries=learnings_cfg.context_assembler_max_entries,
            )
            if not value:
                continue
            tokens = estimate_tokens(value)
            if tokens <= limit:
                packet[layer] = value
                remaining -= tokens
            else:
                logger.debug(
                    "Context layer omitted for size",
                    extra={
                        "mission_id": mission_id,
                        "mission_run_id": mission_run_id,
                        "layer": layer,
                        "tokens": tokens,
                        "limit": limit,
                    },
                )

        logger.debug(
            "Context assembled",
            extra={
                "mission_id": mission_id,
                "mission_run_id": mission_run_id,
                "budget": budget,
                "used": budget - remaining,
                "layers": list(packet.keys()),
            },
        )
        return packet

    async def _layer_value(
        self,
        layer: str,
        *,
        mission_id: str,
        domain_tags: list[str] | None,
        mission_run_id: str | None,
        limit: int,
        max_entries: int,
    ) -> Any:
        """The rendered value of one optional layer, sized to ``limit`` where it can be.

        None when the layer does not apply.
        """
        if layer in ("previous_run_digest", "context_delta"):
            if mission_run_id is None:
                return None
            run_packet = await self._run_packet(mission_run_id)
            run_layer = getattr(run_packet, layer)
            if run_layer is None:
                return None
            if layer == "previous_run_digest":
                return self._fit_digest(run_layer, limit)
            return run_layer.model_dump(mode="json")
        if layer == "code_map":
            if not self._is_coding_task(domain_tags):
                return None
            return self._load_code_map_markdown(limit)
        if layer == "learnings":
            return await self._assemble_learnings(mission_id, domain_tags, limit, max_entries)
        if not domain_tags:
            return None
        return await self._assemble_history(mission_id, domain_tags, limit)

    @staticmethod
    def _fit_digest(digest: PreviousRunDigest, limit: int) -> dict | None:
        """The digest dump with its summary shortened until the whole dump fits ``limit``.

        RunMemoryService bounds only the summary (previous_digest_max_chars);
        open_items, metrics and JSON framing are measured here too. Returns
        None when the dump does not fit even with an empty summary.
        """
        dump = digest.model_dump(mode="json")
        summary: str = dump["summary"]
        keep = len(summary)
        while True:
            dump["summary"] = summary[:keep]
            overshoot = estimate_tokens(dump) - limit
            if overshoot <= 0:
                return dump
            if keep == 0:
                return None
            keep = max(0, keep - overshoot * 4)

    async def _run_packet(self, mission_run_id: str) -> RunContextPacket:
        """The run's context packet, built once per run id for this assembler."""
        packet = self._packets.get(mission_run_id)
        if packet is None:
            packet = await self._run_memory.build_context_packet(mission_run_id)
            self._packets[mission_run_id] = packet
        return packet

    @staticmethod
    def _is_coding_task(domain_tags: list[str] | None) -> bool:
        """Determine if this task needs codebase structural context.

        Conservative: includes Code Map when domain_tags is empty or None.
        """
        if not domain_tags:
            return True
        return bool(set(domain_tags) & _CODING_TAGS)

    def _load_code_map_markdown(self, max_tokens: int | None = None) -> str | None:
        """Load the pre-rendered Code Map Markdown via the injected loader."""
        if self._code_map_loader is None:
            return None

        content = self._code_map_loader.get_markdown()

        if content and max_tokens:
            token_count = estimate_tokens(content)
            if token_count > max_tokens:
                code_map_json = self._code_map_loader.get_json()
                if code_map_json:
                    from modules.backend.services.code_map.assembler import render_for_agent

                    content = render_for_agent(code_map_json, max_tokens)

        return content

    async def _assemble_learnings(
        self,
        mission_id: str,
        domain_tags: list[str] | None,
        cap: int,
        max_entries: int,
    ) -> list[dict] | None:
        """Learnings by confidence, appended while their cumulative tokens stay within cap.

        Mission learnings always; platform-promoted learnings only when the
        task has domain_tags. Merged and deduplicated by id.
        """
        learnings = await self._learning_repo.list_by_mission(
            mission_id, domain_tags=domain_tags, limit=max_entries
        )
        if domain_tags:
            learnings = learnings + await self._learning_repo.list_platform_promoted(
                domain_tags=domain_tags, limit=max_entries
            )

        seen: set[str] = set()
        merged: list[dict] = []
        for learning in sorted(learnings, key=lambda x: x.confidence, reverse=True):
            if learning.id in seen:
                continue
            seen.add(learning.id)
            entry = {
                "kind": learning.kind,
                "title": learning.title,
                "recommendation": learning.recommendation,
                "confidence": learning.confidence,
                "domain_tags": learning.domain_tags,
            }
            if estimate_tokens([*merged, entry]) > cap:
                break
            merged.append(entry)
            if len(merged) >= max_entries:
                break

        return merged or None

    async def _assemble_history(
        self,
        mission_id: str,
        domain_tags: list[str],
        remaining_budget: int,
    ) -> dict[str, Any]:
        """Assemble Layer 2 history within remaining token budget."""
        history: dict[str, Any] = {}

        # Recent failures first — agents must not repeat mistakes
        failures = await self._history_service.get_recent_failures(
            mission_id,
            domain_tags=domain_tags,
            limit=3,
        )
        if failures:
            failure_tokens = estimate_tokens(failures)
            if failure_tokens <= remaining_budget:
                history["recent_failures"] = failures
                remaining_budget -= failure_tokens

        # Recent executions in same domain
        if remaining_budget > 200:
            executions = await self._history_service.get_recent_task_executions(
                mission_id,
                domain_tags=domain_tags,
                limit=5,
            )
            if executions:
                exec_tokens = estimate_tokens(executions)
                if exec_tokens <= remaining_budget:
                    history["recent_executions"] = executions

        return history
