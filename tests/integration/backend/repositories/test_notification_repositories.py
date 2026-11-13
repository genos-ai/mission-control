"""Recipient, delivery and channel identity repositories (Plan 88, 88.4.3)."""

from uuid import uuid7

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.notification import (
    MissionNotificationRecipient,
    NotificationDeliveryStatus,
    NotificationKind,
)
from modules.backend.models.user_channel_identity import (
    ChannelKind,
    UserChannelIdentity,
)
from modules.backend.repositories.mission_notification_recipient import (
    MissionNotificationRecipientRepository,
)
from modules.backend.repositories.notification_delivery import (
    NotificationDeliveryRepository,
)
from modules.backend.repositories.user_channel_identity import (
    UserChannelIdentityRepository,
)
from tests.integration.backend.api.helpers import create_mission


async def test_list_for_kind_matches_lowercase_value(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, f"kinds-{uuid7()}", test_user.id)
    db_session.add(
        MissionNotificationRecipient(
            mission_id=mission.id,
            user_id=test_user.id,
            channel=ChannelKind.TELEGRAM,
            kinds=[NotificationKind.RUN_FAILED.value],
        )
    )
    await db_session.flush()
    repo = MissionNotificationRecipientRepository(db_session)

    [recipient] = await repo.list_for_kind(mission.id, NotificationKind.RUN_FAILED)
    assert recipient.user_id == test_user.id
    assert await repo.list_for_kind(mission.id, NotificationKind.RUN_SUCCEEDED) == []
    assert await repo.get_for_mission(mission.id, recipient.id) is recipient
    other = await create_mission(db_session, f"kinds-other-{uuid7()}", test_user.id)
    assert await repo.get_for_mission(other.id, recipient.id) is None


async def test_delivery_get_or_create_is_idempotent(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, f"deliveries-{uuid7()}", test_user.id)
    key = f"run_failed:{uuid7()}:{test_user.id}:telegram"
    repo = NotificationDeliveryRepository(db_session)
    args = dict(
        dedupe_key=key,
        mission_id=mission.id,
        kind=NotificationKind.RUN_FAILED,
        recipient_user_id=test_user.id,
        channel=ChannelKind.TELEGRAM,
        mission_run_id=None,
    )

    first = await repo.get_or_create(**args)
    assert first.status == NotificationDeliveryStatus.FAILED
    assert first.attempt_count == 0
    second = await repo.get_or_create(**args)
    assert second.id == first.id


async def test_identity_reads_respect_verification(
    db_session: AsyncSession, test_user, test_user_2
) -> None:
    unverified = UserChannelIdentity(
        user_id=test_user.id, channel=ChannelKind.TELEGRAM, external_id="1001"
    )
    verified = UserChannelIdentity(
        user_id=test_user_2.id,
        channel=ChannelKind.TELEGRAM,
        external_id="2002",
        verified_at=utc_now(),
    )
    db_session.add_all([unverified, verified])
    await db_session.flush()
    repo = UserChannelIdentityRepository(db_session)

    assert await repo.get_verified_by_external(ChannelKind.TELEGRAM, "1001") is None
    assert await repo.get_verified_for_user(test_user.id, ChannelKind.TELEGRAM) is None
    assert await repo.get_by_user(test_user.id, ChannelKind.TELEGRAM, verified_only=False)
    assert (await repo.get_verified_by_external(ChannelKind.TELEGRAM, "2002")) is verified
    assert await repo.get_for_user_by_id(test_user.id, verified.id) is None
    assert [i.id for i in await repo.list_by_user(test_user_2.id)] == [verified.id]

    assert await repo.delete_unverified(test_user.id, ChannelKind.TELEGRAM, "2002") == 1
    assert await repo.get_verified_for_user(test_user_2.id, ChannelKind.TELEGRAM) is verified
