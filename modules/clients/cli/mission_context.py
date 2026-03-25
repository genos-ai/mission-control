"""
CLI mission context resolution.

Provides the @with_mission decorator that resolves mission_id from
--mission flag or the authenticated user's current_mission_id in the DB.
"""

import asyncio
import functools

import click

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

CLI_SERVICE_ACCOUNT_ID = "system:cli"


def _resolve_current_mission_id() -> str | None:
    """Read the CLI service account's current_mission_id from the DB."""
    async def _fetch() -> str | None:
        from modules.backend.repositories.user import UserRepository
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            repo = UserRepository(db)
            user = await repo.get_by_id_or_none(CLI_SERVICE_ACCOUNT_ID)
            if user is None:
                return None
            return user.current_mission_id

    try:
        return asyncio.run(_fetch())
    except Exception:
        logger.debug("Could not resolve current mission from DB", exc_info=True)
        return None


def with_mission(f):
    """Decorator that resolves mission_id from --mission flag or user profile.

    Adds --mission/-m option to the command. If not provided, reads the
    CLI service account's current_mission_id from the database. Raises
    UsageError if neither is available.

    The decorated function receives ``mission_id: str`` as a keyword argument.
    """
    @click.option(
        "--mission", "-m", "mission_id",
        default=None,
        help="Mission ID (uses current mission if not specified).",
    )
    @functools.wraps(f)
    def wrapper(*args, mission_id: str | None = None, **kwargs):
        if not mission_id:
            mission_id = _resolve_current_mission_id()
        if not mission_id:
            raise click.UsageError(
                "No mission specified. Use 'mission use <id>' to set a default."
            )
        return f(*args, mission_id=mission_id, **kwargs)

    return wrapper
