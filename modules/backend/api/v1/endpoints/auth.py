"""
Auth API Endpoints.

Public endpoints for login, token refresh, and authenticated endpoints
for API key management and password changes.
"""

from fastapi import APIRouter, Header

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SseTokenResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    build_api_key_create_response,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.user import (
    SetCurrentMissionRequest,
    UpdateProfileRequest,
    UserResponse,
)

router = APIRouter()


@router.post("/login", response_model=ApiResponse, summary="Login with email and password")
async def login(
    body: LoginRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Authenticate with email/password, receive JWT token pair."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    result = await service.login(email=body.email, password=body.password)

    return ApiResponse(
        success=True,
        data=LoginResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            user=UserResponse.from_user(result["user"]),
        ).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.post("/refresh", response_model=ApiResponse, summary="Refresh JWT tokens")
async def refresh_token(
    body: TokenRefreshRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Exchange a refresh token for a new token pair."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    result = await service.refresh_token(body.refresh_token)

    return ApiResponse(
        success=True,
        data=TokenRefreshResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
        ).model_dump(),
        metadata={"request_id": request_id},
    )


def _bearer_token(authorization: str | None) -> str | None:
    """The token of an ``Authorization: Bearer`` header, or None for any other scheme."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:]


@router.post("/logout", response_model=ApiResponse, summary="End the current session")
async def logout(
    _: CurrentUser,  # authenticates the request; the session comes from the bearer token itself
    db: DbSession,
    request_id: RequestId,
    authorization: str | None = Header(None),
) -> ApiResponse:
    """Revoke the session behind the bearer token, so its refresh tokens stop working too."""
    from modules.backend.services.auth import AuthService

    # An API key has no session to end; only a login JWT does.
    access_token = _bearer_token(authorization)
    if access_token is None:
        raise AuthenticationError("A bearer token is required to log out")

    await AuthService(db).logout(access_token)

    return ApiResponse(
        success=True,
        data={"message": "Logged out"},
        metadata={"request_id": request_id},
    )


@router.post(
    "/sse-token", response_model=ApiResponse, summary="Exchange JWT for short-lived SSE token"
)
async def create_sse_token(
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
    authorization: str | None = Header(None),
) -> ApiResponse:
    """Exchange a valid JWT for a short-lived, single-use SSE token.

    EventSource cannot set custom headers, so SSE endpoints accept a
    ``?token=`` query parameter. Rather than passing the long-lived JWT
    directly, callers exchange it here for a 30-second, single-use token
    stored in Redis. The token is bound to the login session it was minted
    from, so ending that session also ends it. An API key has no session to
    bind to; its token is bound to the user's token version only.
    """
    import json
    import uuid

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.exceptions import ExternalServiceError
    from modules.backend.core.logging import get_logger

    logger = get_logger(__name__)
    from modules.backend.services.auth import AuthService, SessionIdentity

    sse_token = str(uuid.uuid4())
    ttl = 30
    access_token = _bearer_token(authorization)
    if access_token:
        identity = await AuthService(db).session_identity_of(access_token)
    else:
        identity = SessionIdentity(current_user.id, None, current_user.token_version)

    # The opaque UUID is meaningless without the Redis side of the handshake
    # — _resolve_sse_token() reads it back to authenticate the SSE stream.
    # If we cannot store the binding, fail the request so the client retries
    # rather than holding a token that will reject on connect.
    try:
        redis = AsyncRedis.from_url(get_redis_url())
        try:
            await redis.set(
                f"sse_token:{sse_token}",
                json.dumps(
                    {
                        "user_id": identity.user_id,
                        "session_id": identity.session_id,
                        "token_version": identity.token_version,
                    }
                ),
                ex=ttl,
            )
        finally:
            await redis.aclose()
    except Exception as exc:
        # non-critical for mission-event visibility — this has no
        # mission_id/event_bus context (auth token issuance, not
        # mission-scoped) and re-raises immediately below, so the
        # failure is visible to the caller via the HTTP error response.
        logger.warning("Redis unavailable for SSE token storage", exc_info=True)
        raise ExternalServiceError("SSE token store unavailable, retry shortly") from exc

    return ApiResponse(
        success=True,
        data=SseTokenResponse(token=sse_token, expires_in=ttl).model_dump(),
        metadata={"request_id": request_id},
    )


@router.get("/me", response_model=ApiResponse, summary="Get current user")
async def get_me(
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Return the current authenticated user's info."""
    return ApiResponse(
        success=True,
        data=UserResponse.from_user(current_user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.patch("/me", response_model=ApiResponse, summary="Update own profile")
async def update_me(
    body: UpdateProfileRequest,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update the current user's own profile (display name only)."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    user = await service.update_user(
        user_id=current_user.id,
        requesting_user=current_user,
        display_name=body.display_name,
    )

    return ApiResponse(
        success=True,
        data=UserResponse.from_user(user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.put("/me/current-mission", response_model=ApiResponse, summary="Set current mission")
async def set_current_mission(
    body: SetCurrentMissionRequest,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Set or clear the current user's active mission."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    user = await service.set_current_mission(
        user_id=current_user.id,
        mission_id=body.mission_id,
        requesting_user=current_user,
    )

    return ApiResponse(
        success=True,
        data=UserResponse.from_user(user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.post("/api-keys", response_model=ApiResponse, summary="Create API key")
async def create_api_key(
    body: ApiKeyCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a new API key for the current user."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    full_key, api_key = await service.create_api_key(
        user_id=current_user.id,
        name=body.name,
        expires_in_days=body.expires_in_days,
        requesting_user=current_user,
    )

    return ApiResponse(
        success=True,
        data=build_api_key_create_response(full_key, api_key).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.get("/api-keys", response_model=ApiResponse, summary="List own API keys")
async def list_api_keys(
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """List all API keys for the current user."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    keys = await service.list_api_keys(
        user_id=current_user.id,
        requesting_user=current_user,
    )

    return ApiResponse(
        success=True,
        data=[ApiKeyResponse.model_validate(k).model_dump(mode="json") for k in keys],
        metadata={"request_id": request_id},
    )


@router.delete("/api-keys/{key_id}", response_model=ApiResponse, summary="Revoke own API key")
async def revoke_api_key(
    key_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Revoke one of the current user's API keys."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    await service.revoke_api_key(key_id=key_id, requesting_user=current_user)

    return ApiResponse(
        success=True,
        data={"message": "API key revoked"},
        metadata={"request_id": request_id},
    )


@router.post("/change-password", response_model=ApiResponse, summary="Change own password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Change the current user's password."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    await service.change_password(
        user_id=current_user.id,
        old_password=body.old_password,
        new_password=body.new_password,
        requesting_user=current_user,
    )

    return ApiResponse(
        success=True,
        data={"message": "Password changed"},
        metadata={"request_id": request_id},
    )
