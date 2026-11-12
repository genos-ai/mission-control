"""
Mission Context Manager.

Reads, writes, and versions the Mission Context Document (MCD).
Includes in-memory cache, size tracking, and seed MCD creation.
"""

import copy
import json as _json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import estimate_tokens, utc_now
from modules.backend.models.mission_context import (
    ChangeType,
    ContextChange,
    ContextMilestone,
    MissionContext,
)
from modules.backend.repositories.mission_context import (
    ContextChangeRepository,
    ContextMilestoneRepository,
    MissionContextRepository,
)
from modules.backend.services.base import BaseService
from modules.backend.services.mcd_pruning import mcd_size_bytes

logger = get_logger(__name__)


def _load_mcd_limits() -> tuple[int, int]:
    """Load MCD size limits from missions config."""
    from modules.backend.core.config import get_app_config

    cfg = get_app_config().missions
    return cfg.pcd_max_size_bytes, cfg.pcd_target_size_bytes


def _get_max_size() -> int:
    return _load_mcd_limits()[0]


def _get_target_size() -> int:
    return _load_mcd_limits()[1]


# In-memory cache: mission_id -> (context_data, version, timestamp)
_cache: dict[str, tuple[dict, int, float]] = {}
_CACHE_TTL_SECONDS = 30.0

_SENTINEL = object()

# Restricted paths that agents cannot modify
_RESTRICTED_PATHS = {"version", "last_updated", "last_updated_by"}


def _get_nested(data: dict, path: str) -> Any:
    """Get a value from a nested dict using dot notation.

    Returns _SENTINEL if path not found.
    """
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            if key == "-":
                return _SENTINEL
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return _SENTINEL
        else:
            return _SENTINEL
    return current


def _set_nested(data: dict, path: str, value: Any) -> None:
    """Set a value in a nested dict using dot notation.

    Creates intermediate dicts as needed.
    """
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    final_key = keys[-1]
    if final_key == "-" and isinstance(current, list):
        current.append(value)
    else:
        current[final_key] = value


def _delete_nested(data: dict, path: str) -> Any:
    """Delete a value from a nested dict. Returns the old value."""
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None

    final_key = keys[-1]
    if isinstance(current, dict) and final_key in current:
        return current.pop(final_key)
    elif isinstance(current, list):
        try:
            idx = int(final_key)
            return current.pop(idx)
        except (ValueError, IndexError):
            return None
    return None


class MissionContextManager(BaseService):
    """Service for MCD read/write with versioning, caching, and size tracking."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._context_repo = MissionContextRepository(session)
        self._change_repo = ContextChangeRepository(session)
        self._milestone_repo = ContextMilestoneRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["MissionContextManager", None]:
        """Create a MissionContextManager with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield MissionContextManager(db)
            await db.commit()

    def _build_seed_mcd(self, mission_name: str, description: str) -> dict:
        """Build the initial seed MCD for a new mission."""
        return {
            "version": 1,
            "last_updated": "",
            "last_updated_by": "system:mission_creation",
            "identity": {
                "name": mission_name,
                "purpose": description,
                "tech_stack": [],
                "repo_structure": {},
            },
            "architecture": {
                "components": {},
                "data_flow": "",
                "conventions": {},
            },
            "decisions": [],
            "current_state": {
                "active_workstreams": [],
                "recent_milestones": [],
                "known_issues": [],
                "next_priorities": [],
            },
            "guardrails": [],
        }

    async def create_context(
        self,
        mission_id: str,
        mission_name: str,
        description: str,
    ) -> MissionContext:
        """Create a seed MCD for a new mission."""
        seed = self._build_seed_mcd(mission_name, description)
        serialized = _json.dumps(seed, ensure_ascii=False)
        ctx = await self._context_repo.create(
            mission_id=mission_id,
            context_data=seed,
            version=1,
            size_characters=len(serialized),
            size_tokens=estimate_tokens(serialized),
        )
        _cache[mission_id] = (seed, 1, time.monotonic())
        return ctx

    async def get_context(self, mission_id: str) -> dict:
        """Get the MCD for a mission. Uses in-memory cache with TTL.

        Always returns a deep copy so callers cannot corrupt
        the cache or the SQLAlchemy-tracked object.
        """
        cached = _cache.get(mission_id)
        if cached:
            data, version, ts = cached
            if time.monotonic() - ts < _CACHE_TTL_SECONDS:
                return copy.deepcopy(data)

        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            return {}

        data = copy.deepcopy(ctx.context_data)
        _cache[mission_id] = (data, ctx.version, time.monotonic())
        return copy.deepcopy(data)

    async def get_context_with_version(
        self,
        mission_id: str,
    ) -> tuple[dict, int]:
        """Get MCD content and version (for optimistic concurrency)."""
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            return {}, 0
        return ctx.context_data, ctx.version

    async def get_context_size(self, mission_id: str) -> dict:
        """Get MCD size metrics."""
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        max_characters = _get_max_size()
        if ctx is None:
            return {
                "size_characters": 0,
                "size_tokens": 0,
                "version": 0,
                "pct_of_max": 0.0,
                "max_characters": max_characters,
            }
        return {
            "size_characters": ctx.size_characters,
            "size_tokens": ctx.size_tokens,
            "version": ctx.version,
            "pct_of_max": (ctx.size_characters / max_characters) * 100,
            "max_characters": max_characters,
        }

    async def apply_updates(
        self,
        mission_id: str,
        updates: list[dict],
        *,
        agent_id: str | None,
        task_id: str | None,
        mission_run_id: str | None,
        reason: str,
    ) -> tuple[int, list[str]]:
        """Apply context updates to the MCD.

        The MCD row is locked until the caller commits, so writers serialise.
        Every inserted ContextChange carries the MCD's own mission_id plus
        mission_run_id, task_id and agent_id. ``reason`` is the batch reason;
        an update's own ``reason`` key wins.

        Returns (new_version, list_of_errors). Per-update errors are skipped
        and returned; a version conflict raises ConflictError.
        """
        ctx = await self._context_repo.get_by_mission_id_for_update(mission_id)
        if ctx is None:
            return 0, ["MissionContext not found for mission"]

        current_version = ctx.version
        errors: list[str] = []
        data = copy.deepcopy(ctx.context_data)

        applied_changes: list[dict] = []

        for update in updates:
            op = update.get("op")
            path = update.get("path", "")
            value = update.get("value")
            change_reason = update.get("reason") or reason

            root_key = path.split(".")[0] if path else ""
            if root_key in _RESTRICTED_PATHS:
                errors.append(f"Restricted path: {path}")
                continue

            if op == "remove" and path.startswith("guardrails") and agent_id:
                errors.append(f"Agents cannot remove guardrails: {path}")
                continue

            old_value = None
            change_type = None

            if op == "add":
                old_value = _get_nested(data, path)
                if old_value is _SENTINEL:
                    old_value = None
                _set_nested(data, path, value)
                change_type = ChangeType.ADD

            elif op == "replace":
                old_value = _get_nested(data, path)
                if old_value is _SENTINEL:
                    errors.append(f"Path not found for replace: {path}")
                    continue
                if old_value == value:
                    errors.append(f"No-op replace (value unchanged): {path}")
                    continue
                _set_nested(data, path, value)
                change_type = ChangeType.REPLACE

            elif op == "remove":
                old_value = _delete_nested(data, path)
                if old_value is None:
                    errors.append(f"Path not found for remove: {path}")
                    continue
                change_type = ChangeType.REMOVE

            else:
                errors.append(f"Unknown operation: {op}")
                continue

            applied_changes.append(
                {
                    "change_type": change_type,
                    "path": path,
                    "old_value": old_value if not isinstance(old_value, type(_SENTINEL)) else None,
                    "new_value": value,
                    "reason": change_reason,
                }
            )

        data["version"] = current_version + 1
        data["last_updated"] = utc_now().isoformat()
        data["last_updated_by"] = agent_id or "system"

        size_bytes = mcd_size_bytes(data)
        max_bytes = _get_max_size()
        if size_bytes > max_bytes:
            return current_version, [
                f"MCD would exceed size cap: {size_bytes} > {max_bytes} bytes. "
                "Prune before applying more updates."
            ]

        serialized = _json.dumps(data, ensure_ascii=False)
        new_size = len(serialized)
        new_version = current_version + 1
        rows_updated = await self._context_repo.update_context(
            mission_id=mission_id,
            context_data=data,
            new_version=new_version,
            size_characters=new_size,
            size_tokens=estimate_tokens(serialized),
        )
        if rows_updated == 0:
            raise ConflictError("MCD version conflict")

        for change in applied_changes:
            await self._change_repo.create(
                context_id=ctx.id,
                version=new_version,
                change_type=change["change_type"],
                path=change["path"],
                old_value=change["old_value"],
                new_value=change["new_value"],
                agent_id=agent_id,
                mission_id=mission_id,
                task_id=task_id,
                mission_run_id=mission_run_id,
                reason=change["reason"],
            )

        _cache.pop(mission_id, None)

        self._log_operation(
            "MCD updated",
            mission_id=mission_id,
            new_version=new_version,
            size_bytes=size_bytes,
            updates_applied=len(applied_changes),
            errors=len(errors),
        )

        return new_version, errors

    async def get_changes_between(
        self,
        mission_id: str,
        after_version: int,
        up_to_version: int,
        limit: int,
    ) -> list[ContextChange]:
        """MCD changes with after_version < version <= up_to_version, newest first.

        [] when no MCD exists.
        """
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            return []
        return await self._change_repo.list_between(ctx.id, after_version, up_to_version, limit)

    async def count_changes_between(
        self,
        mission_id: str,
        after_version: int,
        up_to_version: int,
    ) -> int:
        """Count of MCD changes in (after_version, up_to_version]; 0 when no MCD exists."""
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            return 0
        return await self._change_repo.count_between(ctx.id, after_version, up_to_version)

    async def get_history(
        self,
        mission_id: str,
        limit: int = 50,
    ) -> list[ContextChange]:
        """Get recent MCD change history."""
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            return []
        return await self._change_repo.list_by_context(ctx.id, limit=limit)

    # ---- Context Milestones ----

    async def create_milestone(
        self,
        mission_id: str,
        title: str,
        *,
        description: str = "",
        created_by: str = "system",
    ) -> ContextMilestone:
        """Create a named snapshot of the current MCD state."""
        ctx = await self._context_repo.get_by_mission_id(mission_id)
        if ctx is None:
            raise ValueError(f"No MCD found for mission {mission_id}")

        milestone = await self._milestone_repo.create(
            mission_id=mission_id,
            title=title,
            description=description,
            version_snapshot=ctx.version,
            context_snapshot=copy.deepcopy(ctx.context_data),
            created_by=created_by,
        )

        self._log_operation(
            "Context milestone created",
            mission_id=mission_id,
            milestone_id=milestone.id,
            title=title,
            version=ctx.version,
        )
        return milestone

    async def list_milestones(
        self,
        mission_id: str,
        limit: int = 50,
    ) -> list[ContextMilestone]:
        """List milestones for a mission, newest first."""
        return await self._milestone_repo.list_by_mission(mission_id, limit=limit)
