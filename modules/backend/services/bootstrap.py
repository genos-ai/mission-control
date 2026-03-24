"""
Bootstrap Service.

CLI-only operations that run outside the FastAPI lifecycle:
initial admin creation, password resets, and other admin bootstrapping.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.models.user import User
from modules.backend.repositories.api_key import ApiKeyRepository
from modules.backend.repositories.user import UserRepository

logger = get_logger(__name__)


class BootstrapService:
    """CLI-only admin operations: initial setup, password resets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._user_repo = UserRepository(session)
        self._api_key_repo = ApiKeyRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["BootstrapService", None]:
        """Create a BootstrapService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield BootstrapService(db)
            await db.commit()

    async def bootstrap_admin(
        self,
        email: str,
        display_name: str,
        password: str,
    ) -> tuple[User, str]:
        """Create the first admin user with a bootstrap API key.

        Returns:
            Tuple of (user, full_api_key).

        Raises:
            ConflictError: If an admin user already exists.
        """
        existing_admins = await self._user_repo.list_all(
            limit=1, offset=0, role_filter="admin",
        )
        if existing_admins:
            raise ConflictError(
                "Admin user already exists. Use the admin API to create additional users."
            )

        hashed_password = await asyncio.to_thread(security.hash_password, password)

        user = await self._user_repo.create(
            email=email,
            display_name=display_name,
            hashed_password=hashed_password,
            system_role="admin",
        )

        full_key, hashed_key = await asyncio.to_thread(security.generate_api_key)

        await self._api_key_repo.create(
            user_id=user.id,
            name="bootstrap",
            key_prefix=full_key[:8],
            hashed_key=hashed_key,
        )

        logger.info("Admin user bootstrapped", extra={"email": email, "user_id": str(user.id)})
        return user, full_key

    async def reset_password_by_email(self, email: str, new_password: str) -> None:
        """Reset a user's password by email. CLI admin operation.

        Raises:
            NotFoundError: If no user exists with the given email.
        """
        user = await self._user_repo.get_by_email(email)
        if not user:
            raise NotFoundError(f"No user found with email: {email}")

        hashed = await asyncio.to_thread(security.hash_password, new_password)
        await self._user_repo.update(user.id, hashed_password=hashed)

        logger.info("Password reset via CLI", extra={"email": email})
