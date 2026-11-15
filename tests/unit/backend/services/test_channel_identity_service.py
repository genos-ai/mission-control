"""ChannelIdentityService lookups (Plan 88 step 88.4.4, contract 3.1.10)."""

from modules.backend.core.utils import utc_now
from modules.backend.models.user_channel_identity import (
    ChannelKind,
    UserChannelIdentity,
)
from modules.backend.services.channel_identity import ChannelIdentityService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2


async def test_resolve_ignores_unconfirmed(db_session, test_user, test_user_2) -> None:
    db_session.add_all(
        [
            UserChannelIdentity(
                user_id=TEST_USER_ID, channel=ChannelKind.TELEGRAM, external_id="5001"
            ),
            UserChannelIdentity(
                user_id=TEST_USER_ID_2,
                channel=ChannelKind.TELEGRAM,
                external_id="5002",
                verified_at=utc_now(),
            ),
        ]
    )
    await db_session.flush()
    service = ChannelIdentityService(db_session)

    assert await service.resolve(ChannelKind.TELEGRAM, "5001") is None
    assert await service.get_for_user(TEST_USER_ID, ChannelKind.TELEGRAM) is None
    confirmed = await service.resolve(ChannelKind.TELEGRAM, "5002")
    assert confirmed is not None and confirmed.user_id == TEST_USER_ID_2
    assert (await service.get_for_user(TEST_USER_ID_2, ChannelKind.TELEGRAM)).id == confirmed.id
