"""
FastAPI Dependencies.

Shared dependencies for request handling.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.database import get_db_session
from modules.backend.core.exceptions import AuthenticationError, AuthorizationError
from modules.backend.core.idempotency import IdempotencyGuard
from modules.backend.core.logging import get_logger
from modules.backend.models.user import User

logger = get_logger(__name__)

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
# User-based authentication and authorization
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    db: DbSession,
    authorization: str | None = Header(None),
    api_key: str | None = Security(_api_key_header),
) -> User:
    """Resolve the current user from JWT or API key.

    Resolution order:
        1. Authorization: Bearer <jwt> → decode JWT → load user by 'sub' claim
        2. X-API-Key header → prefix lookup + bcrypt verify → load user
        3. X-API-Key matches legacy ADMIN_API_KEY → load first admin user from DB
        4. Else → raise AuthenticationError
    """
    from modules.backend.services.auth import AuthService

    auth_service = AuthService(db)

    # 1. Try JWT Bearer token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        return await auth_service.resolve_jwt(token)

    # 2. Try per-user API key
    if api_key:
        try:
            return await auth_service.resolve_api_key(api_key)
        except AuthenticationError:
            pass  # Fall through to legacy check

        # 3. Legacy ADMIN_API_KEY fallback
        user = await auth_service.resolve_legacy_key(api_key)
        if user:
            return user

    raise AuthenticationError("Authentication required")


async def get_optional_user(
    db: DbSession,
    authorization: str | None = Header(None),
    api_key: str | None = Security(_api_key_header),
) -> User | None:
    """Like get_current_user but returns None instead of raising."""
    try:
        return await get_current_user(db, authorization, api_key)
    except AuthenticationError:
        return None


async def _resolve_sse_token(token: str) -> str | None:
    """Look up a short-lived SSE token in Redis and return the user_id.

    The token is deleted after retrieval (single-use).  Returns ``None``
    when the token is not found or on any Redis error (fail-open so the
    caller can fall back to JWT resolution).
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url

    redis_key = f"sse_token:{token}"
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        user_id: bytes | None = await redis.getdel(redis_key)
        if user_id:
            return user_id.decode()
    except Exception:
        logger.debug("SSE token Redis lookup failed, falling back to auth header", exc_info=True)
    finally:
        await redis.aclose()
    return None


async def get_current_user_sse(
    db: DbSession,
    token: str | None = None,
    authorization: str | None = Header(None),
) -> User:
    """Resolve the current user for SSE endpoints.

    Resolution order:
      1. ``?token`` query param resolved as a short-lived SSE token
         (Redis lookup, single-use, 30 s TTL).
      2. ``?token`` query param resolved as a raw JWT (backwards compat).
      3. ``Authorization: Bearer <jwt>`` header (fetch-based clients, curl).

    API keys are not accepted on streaming endpoints — a stolen JWT is
    scoped by the short-lived access token expiry, while API keys are not.
    """
    from modules.backend.services.auth import AuthService

    auth_service = AuthService(db)

    # 1. Try short-lived SSE token (Redis)
    if token:
        user_id = await _resolve_sse_token(token)
        if user_id:
            from sqlalchemy import select

            from modules.backend.models.user import User as UserModel

            result = await db.execute(select(UserModel).where(UserModel.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                return user

        # 2. Fall back to treating the token as a raw JWT
        return await auth_service.resolve_jwt(token)

    # 3. Authorization header
    if authorization and authorization.lower().startswith("bearer "):
        jwt_token = authorization[7:]
        return await auth_service.resolve_jwt(jwt_token)

    raise AuthenticationError("Authentication required")


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
SseUser = Annotated[User, Depends(get_current_user_sse)]


async def require_admin(user: CurrentUser) -> User:
    """Require that the current user has admin role."""
    if not user.has_role("admin"):
        raise AuthorizationError(f"Requires 'admin' role. Current role: '{user.system_role}'.")
    return user


async def require_sysadmin(user: CurrentUser) -> User:
    """Require that the current user has sysadmin role."""
    if not user.has_role("sysadmin"):
        raise AuthorizationError(f"Requires 'sysadmin' role. Current role: '{user.system_role}'.")
    return user


AdminRole = Annotated[User, Depends(require_admin)]
SysadminRole = Annotated[User, Depends(require_sysadmin)]


# ---------------------------------------------------------------------------
# Resource access checks
# ---------------------------------------------------------------------------
#
# Shared mission/session authorization. Previously copy-pasted into each
# mission sub-router (artifacts, plan, costs, streams); centralised here so
# every endpoint gates the same way. Call from inside a handler after the
# user/db dependencies have resolved — these are plain coroutines, not
# FastAPI dependencies, because they need the path's resource id.


async def require_mission_access(db, mission_id: str, user) -> None:
    """Allow admin, the mission owner, or any mission member.

    Raises AuthorizationError otherwise. NotFoundError from the service
    propagates as-is (handled by the global exception handlers).
    """
    from modules.backend.services.mission import MissionService

    if user.has_role("admin"):
        return
    mission = await MissionService(db).get_mission(mission_id)
    if mission.owner_id == user.id:
        return
    if any(m.user_id == user.id for m in mission.members):
        return
    raise AuthorizationError("You don't have access to this mission")


async def require_mission_owner(db, mission_id: str, user) -> None:
    """Allow only admin or the mission owner (not ordinary members).

    Use for sensitive operations such as membership management, where a
    mere member must not be able to escalate roles or remove others.
    Raises AuthorizationError otherwise.
    """
    from modules.backend.services.mission import MissionService

    if user.has_role("admin"):
        return
    mission = await MissionService(db).get_mission(mission_id)
    if mission.owner_id == user.id:
        return
    raise AuthorizationError("Only the mission owner can perform this action")


async def require_session_access(db, session_id: str, user) -> None:
    """Allow admin, the session owner, or a member of the session's mission.

    Raises AuthorizationError otherwise.
    """
    from modules.backend.core.exceptions import NotFoundError
    from modules.backend.services.session import SessionService

    if user.has_role("admin"):
        return
    try:
        session = await SessionService(db).get_session(session_id)
    except NotFoundError:
        raise AuthorizationError("Session not found or access denied")
    if session.user_id == user.id:
        return
    if session.mission_id:
        try:
            await require_mission_access(db, session.mission_id, user)
            return
        except AuthorizationError:
            pass
    raise AuthorizationError("You don't have access to this session")


# ---------------------------------------------------------------------------
# Idempotency key support
# ---------------------------------------------------------------------------


async def get_idempotency(
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> AsyncIterator[IdempotencyGuard | None]:
    """FastAPI dependency for idempotency key support.

    When the client sends `Idempotency-Key: <uuid>`, yields an
    IdempotencyGuard that endpoints use to check/cache responses.
    Yields None when the header is absent (operation proceeds normally).

    See modules/backend/core/idempotency.py for usage docs.
    """
    if not idempotency_key:
        yield None
        return

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        yield IdempotencyGuard(redis, idempotency_key)
    finally:
        await redis.aclose()


Idempotency = Annotated[IdempotencyGuard | None, Depends(get_idempotency)]
