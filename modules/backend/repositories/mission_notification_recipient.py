"""
Mission Notification Recipient Repository (Plan 88, contract 3.5.2).

Data access for mission_notification_recipients. kinds holds lowercase
NotificationKind values; list_for_kind matches with JSONB key existence.
"""

from sqlalchemy import select

from modules.backend.models.notification import (
    MissionNotificationRecipient,
    NotificationKind,
)
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.base import BaseRepository


class MissionNotificationRecipientRepository(BaseRepository[MissionNotificationRecipient]):
    """Repository for MissionNotificationRecipient rows."""

    model = MissionNotificationRecipient

    async def list_for_kind(
        self, mission_id: str, kind: NotificationKind
    ) -> list[MissionNotificationRecipient]:
        """Recipients of the mission subscribed to this kind (`kinds ? :kind_value`)."""
        stmt = (
            select(MissionNotificationRecipient)
            .where(
                MissionNotificationRecipient.mission_id == mission_id,
                MissionNotificationRecipient.kinds.has_key(kind.value),
            )
            .order_by(MissionNotificationRecipient.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_for_mission(
        self, mission_id: str, recipient_id: str
    ) -> MissionNotificationRecipient | None:
        """The recipient with this id, only if it belongs to the mission."""
        stmt = select(MissionNotificationRecipient).where(
            MissionNotificationRecipient.id == recipient_id,
            MissionNotificationRecipient.mission_id == mission_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_mission(
        self, mission_id: str, channel: ChannelKind | None = None
    ) -> list[MissionNotificationRecipient]:
        """Every recipient of the mission, optionally on one channel, oldest first."""
        stmt = select(MissionNotificationRecipient).where(
            MissionNotificationRecipient.mission_id == mission_id
        )
        if channel is not None:
            stmt = stmt.where(MissionNotificationRecipient.channel == channel)
        stmt = stmt.order_by(MissionNotificationRecipient.created_at)
        return list((await self.session.execute(stmt)).scalars().all())
