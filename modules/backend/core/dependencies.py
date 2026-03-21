"""
FastAPI Dependencies.

Shared dependencies for request handling.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.database import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_request_id(x_request_id: str | None = Header(None)) -> str:
    """Extract or generate request ID from headers."""
    import uuid

    return x_request_id or str(uuid.uuid4())


RequestId = Annotated[str, Depends(get_request_id)]


async def get_event_bus():
    """FastAPI dependency for session event bus."""
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.events.bus import SessionEventBus

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        yield SessionEventBus(redis)
    finally:
        await redis.close()


# ---------------------------------------------------------------------------
# Admin role-based access
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _resolve_role(api_key: str | None) -> str:
    """Resolve an API key or user identifier to a role name.

    Resolution order:
        1. If api_key matches a configured admin key → 'admin'
        2. Otherwise → 'viewer' (default per security.yaml contract)

    The admin API key is stored in .env as ADMIN_API_KEY. When not
    configured, admin endpoints are inaccessible (secure by default).
    """
    from modules.backend.core.config import get_settings

    settings = get_settings()
    admin_key = getattr(settings, "admin_api_key", None)

    if admin_key and api_key and api_key == admin_key:
        return "admin"

    return "viewer"


def require_role(minimum_role: str):
    """FastAPI dependency factory requiring a minimum role level.

    Uses the role hierarchy from security.yaml (higher level = more access).
    """
    async def _check_role(
        api_key: str | None = Security(_api_key_header),
    ) -> str:
        from modules.backend.core.config import get_app_config

        role_name = _resolve_role(api_key)
        roles = get_app_config().security.roles

        required_level = roles.get(minimum_role)
        actual_level = roles.get(role_name)

        if not required_level:
            raise HTTPException(status_code=500, detail=f"Unknown role: {minimum_role}")

        actual = actual_level.level if actual_level else 0

        if actual < required_level.level:
            raise HTTPException(
                status_code=403,
                detail=f"Requires '{minimum_role}' role (level {required_level.level}). "
                       f"Current role: '{role_name}' (level {actual}).",
            )

        return role_name

    return _check_role


async def require_admin(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Concrete admin role dependency. Use in Annotated for stable identity."""
    from modules.backend.core.config import get_app_config

    role_name = _resolve_role(api_key)
    roles = get_app_config().security.roles

    admin_role = roles.get("admin")
    actual_level = roles.get(role_name)

    if not admin_role:
        raise HTTPException(status_code=500, detail="Role 'admin' not configured")

    actual = actual_level.level if actual_level else 0

    if actual < admin_role.level:
        raise HTTPException(
            status_code=403,
            detail=f"Requires 'admin' role (level {admin_role.level}). "
                   f"Current role: '{role_name}' (level {actual}).",
        )

    return role_name


AdminRole = Annotated[str, Depends(require_admin)]
