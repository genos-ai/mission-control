"""
Auth Service.

Handles authentication: login, JWT/API key resolution, key management.
"""

import asyncio
import hmac
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.api_key import ApiKey
from modules.backend.models.user import User
from modules.backend.repositories.api_key import ApiKeyRepository
from modules.backend.repositories.revoked_session import RevokedSessionRepository
from modules.backend.repositories.user import UserRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


@dataclass(frozen=True)
class SessionIdentity:
    """What a credential was issued for: enough to check later that it is still good."""

    user_id: str
    # None for a credential minted from an API key, which has no login session.
    session_id: str | None
    token_version: int


class AuthService(BaseService):
    """Authentication and API key management service."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_repo = UserRepository(session)
        self.api_key_repo = ApiKeyRepository(session)
        self.revoked_session_repo = RevokedSessionRepository(session)

    async def login(self, email: str, password: str) -> dict:
        """Authenticate with email/password, return JWT pair + user."""
        user = await self.user_repo.get_by_email(email)

        if not user or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        if not user.hashed_password:
            raise AuthenticationError("Invalid credentials")

        valid = await asyncio.to_thread(
            security.verify_password,
            password,
            user.hashed_password,
        )
        if not valid:
            raise AuthenticationError("Invalid credentials")

        tokens = self._issue_token_pair(user, session_id=str(uuid4()))

        await self.user_repo.update_last_login(user.id)
        self._log_operation("user_login", user_id=user.id, email=user.email)

        return {**tokens, "user": user}

    def _issue_token_pair(self, user: User, session_id: str) -> dict:
        """Mint an access and refresh token that belong to one login session."""
        return {
            "access_token": security.create_access_token(
                {
                    "sub": user.id,
                    "role": user.system_role,
                    "jti": str(uuid4()),
                    "sid": session_id,
                    "tv": user.token_version,
                }
            ),
            "refresh_token": security.create_refresh_token(
                {
                    "sub": user.id,
                    "jti": str(uuid4()),
                    "sid": session_id,
                    "tv": user.token_version,
                }
            ),
        }

    async def _verified_claims(self, token: str, token_type: str) -> dict:
        """Decode a JWT, requiring its type, a subject and a session that logout has not ended."""
        payload = security.decode_token(token)

        if payload.get("type") != token_type:
            raise AuthenticationError("Invalid token type")

        if not payload.get("sub"):
            raise AuthenticationError("Invalid token")

        # Tokens minted before sessions existed have no sid; they cannot be revoked, so refuse them.
        session_id = payload.get("sid")
        if not session_id:
            raise AuthenticationError("Invalid token")

        # A revocation row is kept one configured refresh lifetime from logout, which outlives
        # every token of the session only if none lives longer. Refusing a refresh token minted
        # under a longer setting keeps that true after the setting is lowered.
        if token_type == TOKEN_TYPE_REFRESH:
            max_lifetime = timedelta(days=get_app_config().security.jwt.refresh_token_expire_days)
            issued_at = payload.get("iat")
            if issued_at is None or payload["exp"] - issued_at > max_lifetime.total_seconds():
                raise AuthenticationError("Invalid token")

        await self._ensure_session_active(session_id)

        return payload

    @staticmethod
    def _ensure_current_version(user: User, payload: dict) -> None:
        """Refuse a token issued before the user's sessions were last ended in bulk."""
        token_version = payload.get("tv")
        if token_version is None:
            raise AuthenticationError("Invalid token")
        if token_version != user.token_version:
            raise AuthenticationError("Session ended")

    async def _ensure_session_active(self, session_id: str) -> None:
        """Raise unless logout has left the session alone."""
        if await self.revoked_session_repo.is_revoked(session_id):
            raise AuthenticationError("Session ended")

    async def session_identity_of(self, access_token: str) -> SessionIdentity:
        """The identity of a valid access token, as bound to a credential derived from it."""
        return (await self.resolve_jwt_session(access_token))[1]

    async def ensure_identity_current(self, identity: SessionIdentity) -> User:
        """The user, if the credential issued for this identity is still good.

        Raises AuthenticationError once the user is deactivated, the session is logged out, or the
        user's sessions were ended in bulk (password change, admin reset, deactivation).
        """
        user = await self.user_repo.get_active(identity.user_id)
        if not user:
            raise AuthenticationError("User not found or inactive")
        if identity.token_version != user.token_version:
            raise AuthenticationError("Session ended")
        if identity.session_id:
            await self._ensure_session_active(identity.session_id)
        return user

    async def logout(self, access_token: str) -> None:
        """End the session of an access token, with every refresh token minted from it."""
        payload = await self._verified_claims(access_token, TOKEN_TYPE_ACCESS)

        # Every token of the session expires within one refresh lifetime of now: a refresh token
        # is refused if it outlives that lifetime (see _verified_claims), and a revoked session
        # can no longer be refreshed.
        refresh_days = get_app_config().security.jwt.refresh_token_expire_days
        expires_at = utc_now() + timedelta(days=refresh_days)
        await self.revoked_session_repo.revoke(payload["sid"], payload["sub"], expires_at)
        # Commit before answering: a 200 must mean the session is ended, not that it will be
        # once the request-scoped session closes.
        await self.session.commit()

        self._log_operation("user_logout", user_id=payload["sub"], session_id=payload["sid"])

    async def purge_expired_revocations(self) -> int:
        """Delete revocation rows whose tokens have all expired. Returns the number deleted."""
        deleted = await self.revoked_session_repo.delete_expired()
        await self.session.commit()
        return deleted

    async def refresh_token(self, refresh_token_str: str) -> dict:
        """Exchange a refresh token for a new token pair in the same session."""
        payload = await self._verified_claims(refresh_token_str, TOKEN_TYPE_REFRESH)

        user = await self.user_repo.get_active(payload["sub"])
        if not user:
            raise AuthenticationError("User not found or inactive")
        self._ensure_current_version(user, payload)

        tokens = self._issue_token_pair(user, session_id=payload["sid"])

        self._log_operation("token_refresh", user_id=user.id)

        return tokens

    async def resolve_api_key(self, raw_key: str) -> User:
        """Resolve a raw API key to a User via prefix narrowing + bcrypt.

        Stashes the key's `scopes` onto the returned User as a transient,
        non-persisted attribute (`resolved_api_key_scopes`) so callers
        that need to enforce scope restrictions (see
        core.dependencies.require_scope) can read it without a second
        lookup, while every existing caller that only cares about the
        User itself is unaffected.
        """
        if len(raw_key) < 8:
            raise AuthenticationError("Invalid API key")

        prefix = raw_key[:8]
        candidates = await self.api_key_repo.get_by_prefix(prefix)

        for candidate in candidates:
            match = await asyncio.to_thread(
                security.verify_api_key,
                raw_key,
                candidate.hashed_key,
            )
            if match:
                if not candidate.user or not candidate.user.is_active:
                    raise AuthenticationError("Account deactivated")

                await self.api_key_repo.update_last_used(candidate.id)
                candidate.user.resolved_api_key_scopes = candidate.scopes
                return candidate.user

        raise AuthenticationError("Invalid API key")

    async def resolve_jwt(self, token: str) -> User:
        """Resolve a JWT access token to a User."""
        return (await self.resolve_jwt_session(token))[0]

    async def resolve_jwt_session(self, token: str) -> tuple[User, SessionIdentity]:
        """Resolve a JWT access token to its User and the identity it was issued for."""
        payload = await self._verified_claims(token, TOKEN_TYPE_ACCESS)

        user = await self.user_repo.get_active(payload["sub"])
        if not user:
            raise AuthenticationError("User not found or inactive")
        self._ensure_current_version(user, payload)

        return user, SessionIdentity(user.id, payload["sid"], payload["tv"])

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        expires_in_days: int | None,
        requesting_user: User,
    ) -> tuple[str, ApiKey]:
        """Create a new API key for a user."""
        self._require_owner_or_admin(user_id, requesting_user, "create API keys")

        full_key, hashed_key = await asyncio.to_thread(security.generate_api_key)
        prefix = full_key[:8]

        expires_at = None
        if expires_in_days:
            expires_at = utc_now() + timedelta(days=expires_in_days)

        api_key = await self.api_key_repo.create(
            user_id=user_id,
            name=name,
            key_prefix=prefix,
            hashed_key=hashed_key,
            expires_at=expires_at,
        )

        self._log_operation(
            "api_key_created",
            user_id=user_id,
            key_name=name,
            requesting_user_id=requesting_user.id,
        )

        return full_key, api_key

    async def list_api_keys(
        self,
        user_id: str,
        requesting_user: User,
    ) -> list[ApiKey]:
        """List API keys for a user."""
        self._require_owner_or_admin(user_id, requesting_user, "view API keys")
        return await self.api_key_repo.list_by_user(user_id)

    async def revoke_api_key(
        self,
        key_id: str,
        requesting_user: User,
    ) -> ApiKey:
        """Revoke an API key."""
        key = await self.api_key_repo.get_by_id(key_id)

        self._require_owner_or_admin(key.user_id, requesting_user, "revoke API keys")

        revoked = await self.api_key_repo.revoke(key_id)

        self._log_operation(
            "api_key_revoked",
            key_id=key_id,
            requesting_user_id=requesting_user.id,
        )

        return revoked

    async def resolve_legacy_key(self, raw_key: str) -> User | None:
        """Resolve the legacy ADMIN_API_KEY to a User, or return None."""
        from modules.backend.core.config import get_settings

        settings = get_settings()
        admin_key = getattr(settings, "admin_api_key", None)

        if not admin_key:
            return None

        if not hmac.compare_digest(raw_key, admin_key):
            return None

        # Find first active admin user
        users = await self.user_repo.list_all(limit=1, offset=0, role_filter="admin")
        if not users:
            return None

        return users[0]
