"""ActionTokenService.issue (Plan 88 step 88.4.4, contracts 3.5.1 and 3.1.10)."""

import hashlib
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.models.action_token import ActionToken, ActionTokenPurpose
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.services.action_token import ActionTokenService
from tests.conftest import TEST_USER_ID


async def test_issue_returns_22_char_raw_and_stores_hash_only(db_session, test_user) -> None:
    before = utc_now()
    raw = await ActionTokenService(db_session).issue(
        purpose=ActionTokenPurpose.CHANNEL_LINK,
        user_id=TEST_USER_ID,
        channel=ChannelKind.TELEGRAM,
        gate_request_id=None,
        ttl_seconds=600,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", raw)
    [row] = (
        (await db_session.execute(select(ActionToken).where(ActionToken.user_id == TEST_USER_ID)))
        .scalars()
        .all()
    )
    assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in {row.token_hash, row.channel_message_ref, row.consumed_ref}
    assert row.consumed_at is None
    assert before + timedelta(seconds=599) <= row.expires_at <= utc_now() + timedelta(seconds=600)
    assert len(f"g:{raw}:a".encode()) <= 64


async def test_issue_gate_decision_requires_gate(db_session, test_user) -> None:
    with pytest.raises(ValidationError):
        await ActionTokenService(db_session).issue(
            purpose=ActionTokenPurpose.GATE_DECISION,
            user_id=TEST_USER_ID,
            channel=ChannelKind.TELEGRAM,
            gate_request_id=None,
            ttl_seconds=600,
        )
