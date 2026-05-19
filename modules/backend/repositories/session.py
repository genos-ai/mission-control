"""Session repository — database queries for sessions and related tables."""

from datetime import datetime

from sqlalchemy import delete, select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.session import (
    Session,
    SessionChannel,
    SessionMessage,
    SessionStatus,
)
from modules.backend.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    """Repository for Session model with lifecycle and channel queries."""

    model = Session

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_active_by_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """Get active and suspended sessions for a user."""
        result = await self.session.execute(
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.status.in_([
                    SessionStatus.ACTIVE,
                    SessionStatus.SUSPENDED,
                ]),
            )
            .order_by(Session.last_activity_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def find_active_for_mission(
        self,
        mission_id: str,
        user_id: str | None = None,
    ) -> Session | None:
        """Find the most recently active session for a mission.

        Returns the single most recent ACTIVE or SUSPENDED session
        scoped to this mission, ordered by last_activity_at DESC.
        When user_id is provided, filters to that user's sessions only.
        """
        conditions = [
            Session.mission_id == mission_id,
            Session.status.in_([
                SessionStatus.ACTIVE,
                SessionStatus.SUSPENDED,
            ]),
        ]
        if user_id:
            conditions.append(Session.user_id == user_id)

        result = await self.session.execute(
            select(Session)
            .where(*conditions)
            .order_by(Session.last_activity_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_by_mission(self, mission_id: str) -> int:
        """Delete all sessions (and their messages/channels) for a mission.

        Deletes children first (messages, channels) then sessions.
        Returns the number of sessions deleted.
        """
        session_ids_q = select(Session.id).where(Session.mission_id == mission_id)

        await self.session.execute(
            delete(SessionMessage).where(SessionMessage.session_id.in_(session_ids_q))
        )
        await self.session.execute(
            delete(SessionChannel).where(SessionChannel.session_id.in_(session_ids_q))
        )
        result = await self.session.execute(
            delete(Session).where(Session.mission_id == mission_id)
        )
        await self.session.flush()
        return result.rowcount

    async def get_by_user(
        self,
        user_id: str | None = None,
        mission_id: str | None = None,
        status_filter: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """Get sessions, optionally filtered by user, mission, agent, and/or status."""
        stmt = select(Session)
        if user_id is not None:
            stmt = stmt.where(Session.user_id == user_id)
        if mission_id is not None:
            stmt = stmt.where(Session.mission_id == mission_id)
        if agent_id is not None:
            stmt = stmt.where(Session.agent_id == agent_id)
        if status_filter:
            stmt = stmt.where(Session.status == status_filter)
        stmt = stmt.order_by(Session.last_activity_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(
        self,
        user_id: str | None = None,
        mission_id: str | None = None,
        status_filter: str | None = None,
    ) -> int:
        """Count sessions, optionally filtered by user, mission, and/or status."""
        stmt = select(func.count()).select_from(Session)
        if user_id is not None:
            stmt = stmt.where(Session.user_id == user_id)
        if mission_id is not None:
            stmt = stmt.where(Session.mission_id == mission_id)
        if status_filter:
            stmt = stmt.where(Session.status == status_filter)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_last_activity(self, session_id: str, new_expires_at: datetime | None = None) -> None:
        """Touch the session's last_activity_at and optionally update expires_at."""
        values: dict = {"last_activity_at": utc_now()}
        if new_expires_at is not None:
            values["expires_at"] = new_expires_at
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(**values)
        )
        await self.session.flush()

    async def find_expired(self, now: datetime | None = None) -> list[Session]:
        """Find sessions past their expires_at that are still ACTIVE or SUSPENDED."""
        if now is None:
            now = utc_now()
        result = await self.session.execute(
            select(Session).where(
                Session.expires_at.isnot(None),
                Session.expires_at <= now,
                Session.status.in_([
                    SessionStatus.ACTIVE,
                    SessionStatus.SUSPENDED,
                ]),
            )
        )
        return list(result.scalars().all())

    # --- Channel queries ---

    async def bind_channel(
        self,
        session_id: str,
        channel_type: str,
        channel_id: str,
    ) -> SessionChannel:
        """Bind a channel to a session. Deactivates any existing binding for this channel."""
        # Deactivate existing bindings for this channel
        await self.session.execute(
            update(SessionChannel)
            .where(
                SessionChannel.channel_type == channel_type,
                SessionChannel.channel_id == channel_id,
                SessionChannel.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
        )

        binding = SessionChannel(
            session_id=session_id,
            channel_type=channel_type,
            channel_id=channel_id,
        )
        self.session.add(binding)
        await self.session.flush()
        await self.session.refresh(binding)
        return binding

    async def unbind_channel(
        self,
        session_id: str,
        channel_type: str,
        channel_id: str,
    ) -> None:
        """Deactivate a channel binding."""
        await self.session.execute(
            update(SessionChannel)
            .where(
                SessionChannel.session_id == session_id,
                SessionChannel.channel_type == channel_type,
                SessionChannel.channel_id == channel_id,
                SessionChannel.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
        )
        await self.session.flush()

    async def get_session_by_channel(
        self,
        channel_type: str,
        channel_id: str,
    ) -> Session | None:
        """Find the active session bound to a channel. Returns None if not found."""
        result = await self.session.execute(
            select(Session)
            .join(
                SessionChannel,
                SessionChannel.session_id == Session.id,
            )
            .where(
                SessionChannel.channel_type == channel_type,
                SessionChannel.channel_id == channel_id,
                SessionChannel.is_active == True,  # noqa: E712
                Session.status.in_([
                    SessionStatus.ACTIVE,
                    SessionStatus.SUSPENDED,
                ]),
            )
        )
        return result.scalar_one_or_none()

    # --- Message queries ---

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sender_id: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        thinking: str | None = None,
        target_agent: str | None = None,
    ) -> SessionMessage:
        """Add a message to a session."""
        msg = SessionMessage(
            session_id=session_id,
            role=role,
            content=content,
            sender_id=sender_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            thinking=thinking,
            target_agent=target_agent,
        )
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg)
        return msg

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        sender_ids: list[str] | None = None,
    ) -> list[SessionMessage]:
        """Get messages for a session, ordered by creation time.

        Args:
            sender_ids: If provided, filter to agent-relevant messages:
                - system messages: always included
                - assistant/tool_call messages: included if sender_id matches
                - user messages: included if target_agent matches, OR if
                  target_agent is NULL (legacy messages before Plan 74)
              This enables per-agent views in shared sessions.
        """
        from sqlalchemy import and_, or_

        stmt = (
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        if sender_ids is not None:
            stmt = stmt.where(
                or_(
                    # System messages: always included
                    SessionMessage.role == "system",
                    # Assistant + tool_call messages: filter by sender
                    SessionMessage.sender_id.in_(sender_ids),
                    # User messages: filter by target_agent (NULL = legacy, show everywhere)
                    and_(
                        SessionMessage.role == "user",
                        or_(
                            SessionMessage.target_agent.in_(sender_ids),
                            SessionMessage.target_agent.is_(None),
                        ),
                    ),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_streaming_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sender_id: str | None = None,
    ) -> SessionMessage:
        """Create a message with status='streaming' for incremental persistence."""
        msg = SessionMessage(
            session_id=session_id,
            role=role,
            content=content,
            sender_id=sender_id,
            status="streaming",
        )
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg)
        return msg

    async def update_message_content(
        self,
        message_id: str,
        content: str,
    ) -> None:
        """Update the content of a streaming message (incremental flush)."""
        from modules.backend.core.utils import utc_now

        result = await self.session.execute(
            select(SessionMessage).where(SessionMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg is not None:
            msg.content = content
            msg.updated_at = utc_now()
            await self.session.flush()

    async def finalize_message(
        self,
        message_id: str,
        content: str,
        *,
        status: str = "complete",
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        thinking: str | None = None,
    ) -> None:
        """Finalize a streaming message — set final content, metadata, and status."""
        from modules.backend.core.utils import utc_now

        result = await self.session.execute(
            select(SessionMessage).where(SessionMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg is not None:
            msg.content = content
            msg.status = status
            msg.model = model
            msg.input_tokens = input_tokens
            msg.output_tokens = output_tokens
            msg.cost_usd = cost_usd
            msg.thinking = thinking
            msg.updated_at = utc_now()
            await self.session.flush()

    async def count_messages(self, session_id: str) -> int:
        """Count messages in a session."""
        result = await self.session.execute(
            select(func.count())
            .select_from(SessionMessage)
            .where(SessionMessage.session_id == session_id)
        )
        return result.scalar_one()
