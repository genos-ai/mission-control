"""
Mission Intent Service.

Manages the append-only intent revision history for a mission.
Current intent = most recent row. Dedup on create prevents chatter.
Publishes MissionIntentRevisedEvent on new revisions.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.mission_intent import IntentSource, MissionIntent
from modules.backend.repositories.mission_intent import MissionIntentRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class MissionIntentService(BaseService):
    """Service for mission intent revisions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._intent_repo = MissionIntentRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["MissionIntentService", None]:
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield MissionIntentService(db)
            await db.commit()

    async def create_intent(
        self,
        mission_id: str,
        intent: str,
        *,
        scope: dict | None = None,
        source: str = IntentSource.SYSTEM.value,
        reason: str = "Initial intent",
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> MissionIntent | None:
        """Create a new intent revision.

        Returns None if the intent is a duplicate of the current one
        (exact match on intent text + scope).
        """
        scope = scope or {}

        # Dedup: skip if identical to current
        current = await self._intent_repo.get_current(mission_id)
        if current and current.intent == intent and current.scope == scope:
            self._log_debug(
                "Intent dedup: identical to current, skipping",
                mission_id=mission_id,
            )
            return None

        # Build summary (first 160 chars or first sentence)
        summary = _build_summary(intent)

        revised_from = current.id if current else None

        new_intent = await self._intent_repo.create(
            mission_id=mission_id,
            intent=intent,
            intent_summary=summary,
            scope=scope,
            source=source,
            revised_from=revised_from,
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
        )

        self._log_operation(
            "Intent revision created",
            mission_id=mission_id,
            intent_id=new_intent.id,
            source=source,
            revised_from=revised_from,
        )

        return new_intent

    async def get_current(self, mission_id: str) -> MissionIntent | None:
        """Get the current (most recent) intent for a mission."""
        return await self._intent_repo.get_current(mission_id)

    async def list_revisions(
        self,
        mission_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionIntent]:
        """List intent revisions, newest first."""
        return await self._intent_repo.list_revisions(
            mission_id, limit=limit, offset=offset,
        )

    async def count_revisions(self, mission_id: str) -> int:
        """Count total revisions for a mission."""
        return await self._intent_repo.count_by_mission(mission_id)


def _build_summary(intent: str, max_chars: int = 160) -> str:
    """Build a one-line summary from the full intent text.

    Takes the first sentence or first max_chars characters,
    whichever is shorter. A sentence ends with punctuation
    followed by a space or end-of-string (not mid-word dots
    like 'software.quality.agent').
    """
    import re
    # Match sentence-ending punctuation followed by whitespace or end
    match = re.search(r'[.!?](?:\s|$)', intent[:max_chars])
    if match and match.start() > 10:  # skip very short "sentences"
        return intent[: match.start() + 1].strip()

    # Truncate
    if len(intent) <= max_chars:
        return intent.strip()
    return intent[:max_chars].strip() + "..."
