"""
User Channel Identity Repository (Plan 88, contract 3.5.2).

Data access for user_channel_identities. Only rows with verified_at set may
resolve for delivery or for decisions; the get_verified_* methods are the
read path for that rule.
"""

from sqlalchemy import delete, or_, select

from modules.backend.models.user_channel_identity import (
    ChannelKind,
    UserChannelIdentity,
)
from modules.backend.repositories.base import BaseRepository


class UserChannelIdentityRepository(BaseRepository[UserChannelIdentity]):
    """Repository for UserChannelIdentity rows."""

    model = UserChannelIdentity

    async def get_by_external(
        self, channel: ChannelKind, external_id: str, *, verified_only: bool
    ) -> UserChannelIdentity | None:
        """The identity for this external account, optionally confirmed rows only."""
        stmt = select(UserChannelIdentity).where(
            UserChannelIdentity.channel == channel,
            UserChannelIdentity.external_id == external_id,
        )
        if verified_only:
            stmt = stmt.where(UserChannelIdentity.verified_at.is_not(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_user(
        self, user_id: str, channel: ChannelKind, *, verified_only: bool
    ) -> UserChannelIdentity | None:
        """The user's identity on this channel, optionally confirmed rows only."""
        stmt = select(UserChannelIdentity).where(
            UserChannelIdentity.user_id == user_id,
            UserChannelIdentity.channel == channel,
        )
        if verified_only:
            stmt = stmt.where(UserChannelIdentity.verified_at.is_not(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_verified_by_external(
        self, channel: ChannelKind, external_id: str
    ) -> UserChannelIdentity | None:
        """The confirmed identity for this external account."""
        return await self.get_by_external(channel, external_id, verified_only=True)

    async def get_verified_for_user(
        self, user_id: str, channel: ChannelKind
    ) -> UserChannelIdentity | None:
        """The user's confirmed identity on this channel."""
        return await self.get_by_user(user_id, channel, verified_only=True)

    async def get_for_user_by_id(
        self, user_id: str, identity_id: str
    ) -> UserChannelIdentity | None:
        """The identity with this id, only if it belongs to the user."""
        stmt = select(UserChannelIdentity).where(
            UserChannelIdentity.id == identity_id,
            UserChannelIdentity.user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> list[UserChannelIdentity]:
        """Every identity of the user, confirmed or not."""
        stmt = (
            select(UserChannelIdentity)
            .where(UserChannelIdentity.user_id == user_id)
            .order_by(UserChannelIdentity.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_unverified(self, user_id: str, channel: ChannelKind, external_id: str) -> int:
        """Delete unconfirmed rows on the channel for this user or this external account."""
        stmt = (
            delete(UserChannelIdentity)
            .where(
                UserChannelIdentity.channel == channel,
                UserChannelIdentity.verified_at.is_(None),
                or_(
                    UserChannelIdentity.user_id == user_id,
                    UserChannelIdentity.external_id == external_id,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
