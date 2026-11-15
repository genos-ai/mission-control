"""
Channel Identity Service (Plan 88 step 88.4.4, contracts 3.5.1 and 3.1.10).

Resolves a platform user's account on an external channel. Both lookups
return confirmed identities only (verified_at IS NOT NULL): an unconfirmed
link never receives a notification and never decides a gate. 88.4.9 adds the
linking methods.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.user_channel_identity import (
    ChannelKind,
    UserChannelIdentity,
)
from modules.backend.repositories.user_channel_identity import (
    UserChannelIdentityRepository,
)
from modules.backend.services.base import BaseService


class ChannelIdentityService(BaseService):
    """Confirmed channel identities of platform users."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._identities = UserChannelIdentityRepository(session)

    async def get_for_user(self, user_id: str, channel: ChannelKind) -> UserChannelIdentity | None:
        """The user's confirmed identity on the channel, or None."""
        return await self._identities.get_verified_for_user(user_id, channel)

    async def resolve(self, channel: ChannelKind, external_id: str) -> UserChannelIdentity | None:
        """The confirmed identity for an external account, or None."""
        return await self._identities.get_verified_by_external(channel, external_id)
