"""
Session Memory Service.

Manages anchored rolling summary compression for long sessions.
Fires when message count since last anchor exceeds a threshold.
Delegates to system.summarization.agent.summarize_session_span().
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.session import Session, SessionMessage
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _get_compression_config() -> dict:
    """Load session_memory config with safe defaults."""
    try:
        from modules.backend.core.config import get_app_config
        cfg = get_app_config().missions.knowledge.session_memory
        return {
            "threshold": cfg.compression_threshold_messages,
            "max_tokens": cfg.summary_max_tokens,
        }
    except Exception:
        return {"threshold": 50, "max_tokens": 8000}


class SessionMemoryService(BaseService):
    """Manages session rolling summary compression."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["SessionMemoryService", None]:
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield SessionMemoryService(db)
            await db.commit()

    async def compress_if_needed(self, session_id: str) -> bool:
        """Check if the session needs compression and compress if so.

        Returns True if compression was performed.
        """
        config = _get_compression_config()
        threshold = config["threshold"]

        # Get current session state
        result = await self.session.execute(
            select(Session).where(Session.id == session_id)
        )
        session_row = result.scalar_one_or_none()
        if not session_row:
            return False

        # Count messages since last anchor
        msg_count_result = await self.session.execute(
            select(func.count())
            .select_from(SessionMessage)
            .where(SessionMessage.session_id == session_id)
        )
        total_messages = msg_count_result.scalar_one() or 0
        anchor = session_row.rolling_summary_anchor

        messages_since_anchor = total_messages - anchor
        if messages_since_anchor < threshold:
            return False

        # Load messages from anchor to current
        msg_result = await self.session.execute(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
            .offset(anchor)
        )
        messages = msg_result.scalars().all()

        if not messages:
            return False

        # Convert to dicts for the summarizer (include sender_id for multi-agent sessions)
        message_dicts = [
            {"role": m.role, "content": m.content[:1000],
             **({"sender_id": m.sender_id} if m.sender_id else {})}
            for m in messages
        ]

        # Compress via the existing summarization agent
        from modules.backend.agents.system.summarization.agent import summarize_session_span

        new_summary = await summarize_session_span(
            message_dicts,
            existing_summary=session_row.rolling_summary or None,
        )

        # Update session
        session_row.rolling_summary = new_summary
        session_row.rolling_summary_anchor = total_messages
        session_row.rolling_summary_version += 1

        await self.session.flush()

        self._log_operation(
            "Session rolling summary compressed",
            session_id=session_id,
            old_anchor=anchor,
            new_anchor=total_messages,
            messages_compressed=messages_since_anchor,
            summary_version=session_row.rolling_summary_version,
        )

        return True

    async def get_rolling_summary(self, session_id: str) -> str | None:
        """Get the current rolling summary for a session."""
        result = await self.session.execute(
            select(Session.rolling_summary)
            .where(Session.id == session_id)
        )
        row = result.scalar_one_or_none()
        return row if row else None
