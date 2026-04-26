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

from modules.backend.models.base import SYSTEM_CLI_ID as CLI_SERVICE_ACCOUNT_ID


async def _async_resolve_current_mission_id() -> str | None:
    """Read the CLI service account's current_mission_id from the DB (async)."""
    from modules.backend.services.user import UserService

    async with UserService.factory() as svc:
        return await svc.get_current_mission_id(CLI_SERVICE_ACCOUNT_ID)


def _resolve_current_mission_id() -> str | None:
    """Read the CLI service account's current_mission_id from the DB (sync wrapper)."""
    try:
        return asyncio.run(_async_resolve_current_mission_id())
    except Exception:
        logger.debug("Could not resolve current mission from DB", exc_info=True)
        return None


async def async_require_mission_id(mission_id: str | None) -> str:
    """Resolve mission_id from explicit value or DB fallback (async).

    Suitable for use inside async action functions that already have
    a running event loop (avoids the nested asyncio.run() problem).
    """
    if not mission_id:
        try:
            mission_id = await _async_resolve_current_mission_id()
        except Exception:
            logger.debug("Could not resolve current mission from DB", exc_info=True)
    if not mission_id:
        raise click.UsageError(
            "No mission specified. Use 'mission use <id>' to set a default."
        )
    return mission_id


def require_mission_id(mission_id: str | None) -> str:
    """Resolve mission_id from explicit value or DB fallback (sync).

    Only safe to call from sync Click handlers that do NOT subsequently
    call asyncio.run(). For handlers that dispatch to async actions via
    run_mission(), use async_require_mission_id() inside the action instead.
    """
    if not mission_id:
        mission_id = _resolve_current_mission_id()
    if not mission_id:
        raise click.UsageError(
            "No mission specified. Use 'mission use <id>' to set a default."
        )
    return mission_id


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
        mission_id = require_mission_id(mission_id)
        return f(*args, mission_id=mission_id, **kwargs)

    return wrapper
