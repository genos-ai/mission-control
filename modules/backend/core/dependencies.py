"""
FastAPI Dependencies.

Shared dependencies for request handling.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.database import get_async_session, get_db_session
from modules.backend.core.exceptions import AuthenticationError, AuthorizationError
from modules.backend.core.idempotency import IdempotencyGuard
from modules.backend.core.logging import get_logger
from modules.backend.models.user import User

if TYPE_CHECKING:
    from modules.backend.services.auth import SessionIdentity

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
    request: Request,
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

    Also stashes the resolved scope restriction (if any) on
    request.state.auth_scopes, so require_scope() can enforce it without
    re-resolving. JWT and legacy-key auth always carry full access
    (None); only a per-user API key can have a non-empty scope list.
    """
    from modules.backend.services.auth import AuthService

    auth_service = AuthService(db)

    # 1. Try JWT Bearer token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        request.state.auth_scopes = None
        return await auth_service.resolve_jwt(token)

    # 2. Try per-user API key
    if api_key:
        try:
            user = await auth_service.resolve_api_key(api_key)
            request.state.auth_scopes = getattr(user, "resolved_api_key_scopes", None)
            return user
        except AuthenticationError:
            logger.debug("Per-user API key check failed, trying legacy key")

        # 3. Legacy ADMIN_API_KEY fallback — off by default (break-glass
        # recovery only); see features.legacy_admin_key_enabled.
        from modules.backend.core.config import get_app_config

        if get_app_config().features.legacy_admin_key_enabled:
            user = await auth_service.resolve_legacy_key(api_key)
            if user:
                logger.warning(
                    "Legacy admin key used",
                    extra={"user_id": user.id, "email": user.email},
                )
                request.state.auth_scopes = None
                return user

    raise AuthenticationError("Authentication required")


async def get_optional_user(
    request: Request,
    db: DbSession,
    authorization: str | None = Header(None),
    api_key: str | None = Security(_api_key_header),
) -> User | None:
    """Like get_current_user but returns None instead of raising."""
    try:
        return await get_current_user(request, db, authorization, api_key)
    except AuthenticationError:
        return None


async def _resolve_sse_token(token: str) -> "SessionIdentity | None":
    """Look up a short-lived SSE token in Redis and return the identity it was minted for.

    The token is deleted after retrieval (single-use). Returns ``None``
    when the token is simply not found (caller falls back to treating it
    as a raw JWT). Raises AuthenticationError on any Redis error instead
    of falling through — a broken Redis must not silently downgrade the
    auth check to "guess it's a JWT" (fail closed, per P16).
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.services.auth import SessionIdentity

    redis_key = f"sse_token:{token}"
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        stored: bytes | None = await redis.getdel(redis_key)
        if stored:
            binding = json.loads(stored)
            return SessionIdentity(
                user_id=binding["user_id"],
                session_id=binding["session_id"],
                token_version=binding["token_version"],
            )
    except Exception as exc:
        raise AuthenticationError("Unable to verify SSE token") from exc
    finally:
        await redis.aclose()
    return None


@dataclass(frozen=True)
class SseSession:
    """The user a stream was opened for, and what to re-check while it stays open."""

    user: User
    identity: "SessionIdentity"


async def get_sse_session(
    token: str | None = None,
    authorization: str | None = Header(None),
) -> SseSession:
    """Resolve the user, and the identity to re-check, for SSE endpoints.

    Resolution order:
      1. ``?token`` query param resolved as a short-lived SSE token
         (Redis lookup, single-use, 30 s TTL).
      2. ``?token`` query param resolved as a raw JWT (backwards compat).
      3. ``Authorization: Bearer <jwt>`` header (fetch-based clients, curl).

    API keys are not accepted on streaming endpoints — a stolen JWT is
    scoped by the short-lived access token expiry, while API keys are not.

    Uses its own short-lived session, not the request-scoped ``DbSession``:
    that one stays open until the response ends, and a stream can run for
    hours, so every open stream would hold a connection from the pool.
    """
    from modules.backend.services.auth import AuthService

    async with get_async_session() as db:
        auth_service = AuthService(db)

        # 1. Try short-lived SSE token (Redis)
        if token:
            identity = await _resolve_sse_token(token)
            if identity:
                # Logout, a password change or a deactivation between minting and connecting
                # must still refuse the stream.
                user = await auth_service.ensure_identity_current(identity)
                return SseSession(user, identity)

            # 2. Fall back to treating the token as a raw JWT
            user, identity = await auth_service.resolve_jwt_session(token)
            return SseSession(user, identity)

        # 3. Authorization header
        if authorization and authorization.lower().startswith("bearer "):
            user, identity = await auth_service.resolve_jwt_session(authorization[7:])
            return SseSession(user, identity)

    raise AuthenticationError("Authentication required")


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
SseAuth = Annotated[SseSession, Depends(get_sse_session)]


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


def require_scope(scope: str):
    """Dependency factory: require the resolved API key to carry `scope`.

    Empty/NULL scopes on the key (the common case — every key created
    before this feature, and any key created without an explicit scope
    list) means full access of the owning user; this is a deliberate,
    documented decision, not a silent fallback. A non-empty scope list
    restricts the key to exactly that set, regardless of the owning
    user's role.
    """

    async def _check(request: Request, user: CurrentUser) -> User:
        scopes = getattr(request.state, "auth_scopes", None)
        if scopes and scope not in scopes:
            raise AuthorizationError(f"API key does not have the required '{scope}' scope.")
        return user

    return _check


# ---------------------------------------------------------------------------
# Resource access checks
# ---------------------------------------------------------------------------
#
# Shared mission/session authorization. Previously copy-pasted into each
# mission sub-router (artifacts, plan, costs, streams); centralised here so
# every endpoint gates the same way. Call from inside a handler after the
# user/db dependencies have resolved — these are plain coroutines, not
# FastAPI dependencies, because they need the path's resource id.


def _require_owner_or_member(mission, user) -> None:
    """The one rule: the mission's owner or a member. Raises AuthorizationError otherwise."""
    if mission.owner_id == user.id:
        return
    if any(m.user_id == user.id for m in mission.members):
        return
    raise AuthorizationError("You don't have access to this mission")


async def require_mission_access(db, mission_id: str, user) -> None:
    """Allow admin, the mission owner, or any mission member.

    Raises AuthorizationError otherwise. NotFoundError from the service
    propagates as-is (handled by the global exception handlers). An admin is
    let through without the mission being looked up; use
    require_existing_mission_access where an unknown mission must be a 404 for
    everyone.
    """
    from modules.backend.services.mission import MissionService

    if user.has_role("admin"):
        return
    _require_owner_or_member(await MissionService(db).get_mission(mission_id), user)


async def require_existing_mission_access(db, mission_id: str, user) -> None:
    """The same rule as require_mission_access, but an unknown mission is a 404 for everyone.

    For endpoints that would otherwise show an admin an empty or all-zero answer for a mission
    that does not exist (costs, plan, artifacts).
    """
    from modules.backend.services.mission import MissionService

    mission = await MissionService(db).get_mission(mission_id)
    if user.has_role("admin"):
        return
    _require_owner_or_member(mission, user)


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
            logger.debug(
                "Session owner check failed and mission-access check also denied",
                extra={"session_id": session_id},
            )
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
