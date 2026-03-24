"""
Auth Service.

Handles authentication: login, JWT/API key resolution, key management.
"""

import asyncio
import hmac
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.api_key import ApiKey
from modules.backend.models.user import User
from modules.backend.repositories.api_key import ApiKeyRepository
from modules.backend.repositories.user import UserRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


class AuthService(BaseService):
    """Authentication and API key management service."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_repo = UserRepository(session)
        self.api_key_repo = ApiKeyRepository(session)

    async def login(self, email: str, password: str) -> dict:
        """Authenticate with email/password, return JWT pair + user."""
        user = await self.user_repo.get_by_email(email)

        if not user or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        if not user.hashed_password:
            raise AuthenticationError("Invalid credentials")

        valid = await asyncio.to_thread(
            security.verify_password, password, user.hashed_password,
        )
        if not valid:
            raise AuthenticationError("Invalid credentials")

        access_token = security.create_access_token({
            "sub": user.id,
            "role": user.system_role,
            "jti": str(uuid4()),
        })
        refresh_token = security.create_refresh_token({
            "sub": user.id,
            "jti": str(uuid4()),
        })

        await self.user_repo.update_last_login(user.id)
        self._log_operation("user_login", user_id=user.id, email=user.email)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user,
        }

    async def refresh_token(self, refresh_token_str: str) -> dict:
        """Exchange a refresh token for a new token pair."""
        payload = security.decode_token(refresh_token_str)

        if payload.get("type") != TOKEN_TYPE_REFRESH:
            raise AuthenticationError("Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token")

        user = await self.user_repo.get_active(user_id)
        if not user:
            raise AuthenticationError("User not found or inactive")

        access_token = security.create_access_token({
            "sub": user.id,
            "role": user.system_role,
            "jti": str(uuid4()),
        })
        new_refresh = security.create_refresh_token({
            "sub": user.id,
            "jti": str(uuid4()),
        })

        self._log_operation("token_refresh", user_id=user.id)

        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
        }

    async def resolve_api_key(self, raw_key: str) -> User:
        """Resolve a raw API key to a User via prefix narrowing + bcrypt."""
        if len(raw_key) < 8:
            raise AuthenticationError("Invalid API key")

        prefix = raw_key[:8]
        candidates = await self.api_key_repo.get_by_prefix(prefix)

        for candidate in candidates:
            match = await asyncio.to_thread(
                security.verify_api_key, raw_key, candidate.hashed_key,
            )
            if match:
                if not candidate.user or not candidate.user.is_active:
                    raise AuthenticationError("Account deactivated")

                await self.api_key_repo.update_last_used(candidate.id)
                return candidate.user

        raise AuthenticationError("Invalid API key")

    async def resolve_jwt(self, token: str) -> User:
        """Resolve a JWT access token to a User."""
        payload = security.decode_token(token)

        if payload.get("type") != TOKEN_TYPE_ACCESS:
            raise AuthenticationError("Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token")

        user = await self.user_repo.get_active(user_id)
        if not user:
            raise AuthenticationError("User not found or inactive")

        return user

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
        self, user_id: str, requesting_user: User,
    ) -> list[ApiKey]:
        """List API keys for a user."""
        self._require_owner_or_admin(user_id, requesting_user, "view API keys")
        return await self.api_key_repo.list_by_user(user_id)

    async def revoke_api_key(
        self, key_id: str, requesting_user: User,
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
