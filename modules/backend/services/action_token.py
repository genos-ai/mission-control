"""
Action Token Service (Plan 88 step 88.4.4, contracts 3.5.1 and 3.1.10).

Issues single-use, expiring tokens carried by channel buttons (gate Approve
and Reject). Only the SHA-256 hex of a token is stored; the raw token is
returned once to the caller that puts it on the button and is never logged.
88.4.9 adds consume.
"""

import base64
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.models.action_token import ActionTokenPurpose
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.action_token import ActionTokenRepository
from modules.backend.services.base import BaseService

TOKEN_BYTES = 16  # contract 3.1.10: 16 random bytes, base64url without padding (22 characters)


def hash_token(raw: str) -> str:
    """The stored form of a raw token: SHA-256 hex."""
    return hashlib.sha256(raw.encode()).hexdigest()


class ActionTokenService(BaseService):
    """Issues action tokens; the raw value leaves this service exactly once."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tokens = ActionTokenRepository(session)

    async def issue(
        self,
        *,
        purpose: ActionTokenPurpose,
        user_id: str,
        channel: ChannelKind,
        gate_request_id: str | None,
        ttl_seconds: int,
    ) -> str:
        """Store a new token's hash and return the raw token.

        A GATE_DECISION token must name its gate and any other purpose must not
        (the table's CHECK constraint, enforced here first for a clear error).
        The row is flushed, not committed; the caller owns the transaction.
        """
        if (purpose == ActionTokenPurpose.GATE_DECISION) != (gate_request_id is not None):
            raise ValidationError("gate_request_id is required exactly for gate_decision tokens")
        if ttl_seconds <= 0:
            raise ValidationError("ttl_seconds must be positive")
        raw = base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).rstrip(b"=").decode()
        await self._tokens.create(
            purpose=purpose,
            token_hash=hash_token(raw),
            user_id=user_id,
            channel=channel,
            gate_request_id=gate_request_id,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
        return raw

    async def set_message_ref(self, raw_tokens: list[str], message_ref: str) -> None:
        """Record the channel message that carries these tokens' buttons."""
        await self._tokens.set_message_ref([hash_token(t) for t in raw_tokens], message_ref)
