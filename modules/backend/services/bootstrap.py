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

    # Well-known service accounts used by internal subsystems.
    # These must exist before any mission can be created.
    SYSTEM_ACCOUNTS = [
        {"id": "system:workflow", "display_name": "Workflow Runner", "system_role": "user"},
        {"id": "system:cli", "display_name": "CLI Runner", "system_role": "user"},
        {"id": "system:scheduler", "display_name": "Scheduler", "system_role": "user"},
    ]

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

    async def ensure_system_accounts(self) -> list[User]:
        """Create well-known service accounts if they don't exist.

        These accounts own missions created by automated subsystems
        (workflow runner, CLI, scheduler) so the mission_members FK
        constraint is satisfied. Idempotent — safe to call repeatedly.

        Returns:
            List of newly created users (empty if all already existed).
        """
        created = []
        for acct in self.SYSTEM_ACCOUNTS:
            existing = await self._user_repo.get_by_id_or_none(acct["id"])
            if existing:
                continue
            user = User(
                id=acct["id"],
                email=f"{acct['id'].replace(':', '-')}@system.local",
                display_name=acct["display_name"],
                system_role=acct["system_role"],
                is_active=True,
                is_service_account=True,
            )
            self._session.add(user)
            created.append(user)
            logger.info("System account created", extra={"id": acct["id"]})

        if created:
            await self._session.flush()
        return created

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
        # Always ensure system service accounts exist
        await self.ensure_system_accounts()

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
