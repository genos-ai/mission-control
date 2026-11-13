"""
Notification Delivery Repository (Plan 88, contract 3.5.2).

Data access for notification_deliveries. get_or_create is idempotent on
dedupe_key, so a retried notification reuses its row.
"""

from uuid import uuid7

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from modules.backend.core.utils import utc_now
from modules.backend.models.notification import (
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationKind,
)
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.base import BaseRepository


class NotificationDeliveryRepository(BaseRepository[NotificationDelivery]):
    """Repository for NotificationDelivery rows."""

    model = NotificationDelivery

    async def get_or_create(
        self,
        dedupe_key: str,
        mission_id: str,
        kind: NotificationKind,
        recipient_user_id: str,
        channel: ChannelKind,
        mission_run_id: str | None,
    ) -> NotificationDelivery:
        """The delivery row for dedupe_key, inserted when absent.

        A new row starts FAILED with attempt_count 0: nothing has been
        delivered yet, so a retry that finds it sends again. NotificationService
        sets the outcome after each attempt; only SENT rows are skipped.
        """
        now = utc_now()
        insert_stmt = (
            pg_insert(NotificationDelivery)
            .values(
                id=str(uuid7()),
                dedupe_key=dedupe_key,
                mission_id=mission_id,
                mission_run_id=mission_run_id,
                kind=kind,
                recipient_user_id=recipient_user_id,
                channel=channel,
                status=NotificationDeliveryStatus.FAILED,
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[NotificationDelivery.dedupe_key])
        )
        await self.session.execute(insert_stmt)
        stmt = select(NotificationDelivery).where(NotificationDelivery.dedupe_key == dedupe_key)
        return (await self.session.execute(stmt)).scalar_one()
