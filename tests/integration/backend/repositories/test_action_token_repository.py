"""ActionTokenRepository (Plan 88, 88.4.3): single-use, expiring, replay-safe consume."""

import hashlib
from datetime import timedelta
from uuid import uuid7

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.action_token import (
    SUPERSEDED_ACTION,
    ActionToken,
    ActionTokenPurpose,
)
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.action_token import ActionTokenRepository
from tests.integration.backend.api.helpers import create_mission


async def _token(db: AsyncSession, user_id: str, expires_in: timedelta) -> str:
    """Insert a CHANNEL_LINK token; return its hash."""
    token_hash = hashlib.sha256(str(uuid7()).encode()).hexdigest()
    db.add(
        ActionToken(
            purpose=ActionTokenPurpose.CHANNEL_LINK,
            token_hash=token_hash,
            user_id=user_id,
            channel=ChannelKind.TELEGRAM,
            expires_at=utc_now() + expires_in,
        )
    )
    await db.flush()
    return token_hash


async def test_consume_single_use(db_session: AsyncSession, test_user) -> None:
    token_hash = await _token(db_session, test_user.id, timedelta(minutes=10))
    repo = ActionTokenRepository(db_session)

    first = await repo.consume(token_hash, "callback-1", utc_now())
    assert first is not None
    assert first.consumed_ref == "callback-1"
    assert first.consumed_at is not None

    assert await repo.consume(token_hash, "callback-2", utc_now()) is None


async def test_consume_rejects_expired(db_session: AsyncSession, test_user) -> None:
    token_hash = await _token(db_session, test_user.id, timedelta(seconds=-1))

    assert await ActionTokenRepository(db_session).consume(token_hash, "cb", utc_now()) is None


async def test_consumed_ref_unique_blocks_replay(db_session: AsyncSession, test_user) -> None:
    first = await _token(db_session, test_user.id, timedelta(minutes=10))
    second = await _token(db_session, test_user.id, timedelta(minutes=10))
    repo = ActionTokenRepository(db_session)
    assert await repo.consume(first, "same-callback", utc_now()) is not None

    savepoint = await db_session.begin_nested()
    with pytest.raises(IntegrityError):
        await repo.consume(second, "same-callback", utc_now())
    await savepoint.rollback()


async def test_consume_siblings_supersedes_unconsumed(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, f"tokens-{uuid7()}", test_user.id)
    gate = GateRequest(
        mission_id=mission.id,
        gate_type="post_run",
        context_json={},
        status=GateRequestStatus.PENDING,
        created_at=utc_now(),
    )
    db_session.add(gate)
    await db_session.flush()
    hashes = []
    for _ in range(2):
        token_hash = hashlib.sha256(str(uuid7()).encode()).hexdigest()
        db_session.add(
            ActionToken(
                purpose=ActionTokenPurpose.GATE_DECISION,
                token_hash=token_hash,
                user_id=test_user.id,
                channel=ChannelKind.TELEGRAM,
                gate_request_id=gate.id,
                expires_at=utc_now() + timedelta(minutes=10),
            )
        )
        hashes.append(token_hash)
    await db_session.flush()
    repo = ActionTokenRepository(db_session)
    assert await repo.consume(hashes[0], "cb-used", utc_now()) is not None

    assert await repo.consume_siblings(gate.id, utc_now()) == 1
    sibling = await db_session.scalar(
        select(ActionToken)
        .where(ActionToken.token_hash == hashes[1])
        .execution_options(populate_existing=True)
    )
    assert sibling.consumed_action == SUPERSEDED_ACTION
    assert sibling.consumed_ref is None
    assert await repo.consume(hashes[1], "cb-late", utc_now()) is None
