"""
Deterministic Mission Context Document compaction (Plan 88, 88.3.3).

MissionContextCompactor plans a compaction and writes its archive rows; it
never writes the mission_contexts row. MissionContextManager owns the version
bump and the context_changes rows, both on the write path (apply_updates) and
at run end (compact). No LLM call is made: the same document, clock date and
change history always give the same result.
"""

import copy
from datetime import timedelta

from modules.backend.core.config import get_app_config
from modules.backend.core.utils import utc_now
from modules.backend.models.mission_context import ChangeType
from modules.backend.repositories.mission_context import (
    ContextChangeRepository,
    ContextMilestoneRepository,
    MissionContextRepository,
)
from modules.backend.repositories.mission_history import (
    MilestoneSummaryRepository,
    MissionDecisionRepository,
)
from modules.backend.schemas.mission_context_compaction import CompactionResult
from modules.backend.services.base import BaseService
from modules.backend.services.mcd_pruning import (
    archive_decision_rows,
    archive_milestone_rows,
    mcd_size_bytes,
    split_decisions_by_age,
    split_milestones,
)

COMPACTION_ACTOR = "system:compaction"

# Bookkeeping roots written by MissionContextManager; never archived.
_BOOKKEEPING_ROOTS = frozenset({"version", "last_updated", "last_updated_by"})


class MissionContextCompactor(BaseService):
    """Plans an MCD compaction and archives what it removes."""

    async def plan(
        self,
        mission_id: str,
        context_id: str,
        current_version: int,
        data: dict,
        target_bytes: int,
    ) -> CompactionResult:
        """Mutate `data` in place until it fits target_bytes or nothing archivable remains.

        Stops as soon as mcd_size_bytes(data) <= target_bytes. Writes ContextMilestone,
        MissionDecision and MilestoneSummary rows in the caller's transaction.
        """
        cfg = get_app_config().missions.compaction
        from_bytes = mcd_size_bytes(data)
        changes: list[dict] = []
        archived_paths: list[str] = []

        await ContextMilestoneRepository(self.session).create(
            mission_id=mission_id,
            title=f"MCD compaction before v{current_version + 1}",
            version_snapshot=current_version,
            context_snapshot=copy.deepcopy(data),
            created_by=COMPACTION_ACTOR,
        )

        if mcd_size_bytes(data) > target_bytes:
            await self._prune_decisions(mission_id, data, cfg.decisions_max_age_days, changes)
        if mcd_size_bytes(data) > target_bytes:
            await self._prune_milestones(mission_id, data, cfg.keep_recent_milestones, changes)
        if mcd_size_bytes(data) > target_bytes:
            await self._archive_roots(
                context_id,
                data,
                set(cfg.protected_roots),
                target_bytes,
                changes,
                archived_paths,
            )

        to_bytes = mcd_size_bytes(data)
        return CompactionResult(
            from_bytes=from_bytes,
            to_bytes=to_bytes,
            changes=changes,
            archived_paths=archived_paths,
            reached_target=to_bytes <= target_bytes,
        )

    async def _prune_decisions(
        self, mission_id: str, data: dict, max_age_days: int, changes: list[dict]
    ) -> None:
        decisions = data.get("decisions", [])
        if not isinstance(decisions, list) or not decisions:
            return
        cutoff = (utc_now() - timedelta(days=max_age_days)).isoformat()[:10]
        keep, archive = split_decisions_by_age(decisions, cutoff)
        if not archive:
            return
        await archive_decision_rows(MissionDecisionRepository(self.session), mission_id, archive)
        data["decisions"] = keep
        changes.append(
            {
                "change_type": ChangeType.PRUNE,
                "path": "decisions",
                "old_value": archive,
                "new_value": keep,
                "reason": f"compaction: decisions older than {max_age_days} days",
            }
        )

    async def _prune_milestones(
        self, mission_id: str, data: dict, keep_recent: int, changes: list[dict]
    ) -> None:
        current_state = data.get("current_state")
        if not isinstance(current_state, dict):
            return
        milestones = current_state.get("recent_milestones", [])
        if not isinstance(milestones, list):
            return
        keep, archive = split_milestones(milestones, keep_recent)
        if not archive:
            return
        await archive_milestone_rows(MilestoneSummaryRepository(self.session), mission_id, archive)
        current_state["recent_milestones"] = keep
        changes.append(
            {
                "change_type": ChangeType.PRUNE,
                "path": "current_state.recent_milestones",
                "old_value": archive,
                "new_value": keep,
                "reason": f"compaction: keep the {keep_recent} most recent milestones",
            }
        )

    async def _archive_roots(
        self,
        context_id: str,
        data: dict,
        protected_roots: set[str],
        target_bytes: int,
        changes: list[dict],
        archived_paths: list[str],
    ) -> None:
        """Remove whole unprotected roots, least recently changed first, until under target."""
        candidates = [k for k in data if k not in protected_roots and k not in _BOOKKEEPING_ROOTS]
        if not candidates:
            return
        ctx = await MissionContextRepository(self.session).get_by_id(context_id)
        last_changed = await ContextChangeRepository(self.session).latest_change_at_by_root(
            context_id
        )
        ordered = sorted(candidates, key=lambda k: (last_changed.get(k, ctx.created_at), k))
        for root in ordered:
            if mcd_size_bytes(data) <= target_bytes:
                return
            section = data.pop(root)
            changes.append(
                {
                    "change_type": ChangeType.ARCHIVE,
                    "path": root,
                    "old_value": section,
                    "new_value": None,
                    "reason": "compaction: archived least recently changed section",
                }
            )
            archived_paths.append(root)
