"""
Action Token Repository (Plan 88, contract 3.5.2).

Data access for action_tokens. consume is the single guarded
UPDATE ... RETURNING that makes a token single-use; ownership and purpose
checks belong to ActionTokenService.
"""

from datetime import datetime

from sqlalchemy import update

from modules.backend.models.action_token import SUPERSEDED_ACTION, ActionToken
from modules.backend.repositories.base import BaseRepository


class ActionTokenRepository(BaseRepository[ActionToken]):
    """Repository for ActionToken rows."""

    model = ActionToken

    async def consume(self, token_hash: str, ref: str, now: datetime) -> ActionToken | None:
        """Mark an unconsumed, unexpired token consumed; None when it is used, expired or unknown.

        A ref already stored on another token violates the UNIQUE consumed_ref
        constraint and raises IntegrityError (replay of the same callback).
        """
        stmt = (
            update(ActionToken)
            .where(
                ActionToken.token_hash == token_hash,
                ActionToken.consumed_at.is_(None),
                ActionToken.expires_at > now,
            )
            .values(consumed_at=now, consumed_ref=ref)
            .returning(ActionToken)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def consume_siblings(self, gate_request_id: str, now: datetime) -> int:
        """Mark every unconsumed token of the gate SUPERSEDED; return the row count."""
        stmt = (
            update(ActionToken)
            .where(
                ActionToken.gate_request_id == gate_request_id,
                ActionToken.consumed_at.is_(None),
            )
            .values(consumed_at=now, consumed_action=SUPERSEDED_ACTION, consumed_ref=None)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
