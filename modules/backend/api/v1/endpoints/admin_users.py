"""
Admin User Management Endpoints.

CRUD operations for users, password management, and API key management
on behalf of any user. All endpoints require admin role.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import AdminRole, DbSession, RequestId
from modules.backend.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    ResetPasswordRequest,
    build_api_key_create_response,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter()


@router.post("/", response_model=ApiResponse, summary="Create user")
async def create_user(
    body: UserCreate,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a new user."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    user = await service.create_user(
        email=body.email,
        display_name=body.display_name,
        password=body.password,
        system_role=body.system_role,
        is_service_account=body.is_service_account,
        requesting_user=_role,
    )

    return ApiResponse(
        success=True,
        data=UserResponse.from_user(user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.get("/", response_model=ApiResponse, summary="List users")
async def list_users(
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApiResponse:
    """List all users."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    users = await service.list_users(
        requesting_user=_role,
        limit=limit,
        offset=offset,
    )

    return ApiResponse(
        success=True,
        data=[UserResponse.from_user(u).model_dump(mode="json") for u in users],
        metadata={"request_id": request_id},
    )


@router.get("/roles", response_model=ApiResponse, summary="List configured roles")
async def list_roles(
    request_id: RequestId,
    _role: AdminRole,
) -> ApiResponse:
    """List all configured roles and their levels."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()
    roles = {
        name: {"level": role.level, "description": role.description}
        for name, role in config.security.roles.items()
    }

    return ApiResponse(
        success=True,
        data={"roles": roles},
        metadata={"request_id": request_id},
    )


@router.get("/{user_id}", response_model=ApiResponse, summary="Get user")
async def get_user(
    user_id: str,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get a user by ID."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    user = await service.get_user(user_id=user_id, requesting_user=_role)

    return ApiResponse(
        success=True,
        data=UserResponse.from_user(user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.patch("/{user_id}", response_model=ApiResponse, summary="Update user")
async def update_user(
    user_id: str,
    body: UserUpdate,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a user's profile or role."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    user = await service.update_user(
        user_id=user_id,
        requesting_user=_role,
        display_name=body.display_name,
        system_role=body.system_role,
        is_active=body.is_active,
    )

    return ApiResponse(
        success=True,
        data=UserResponse.from_user(user).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.delete("/{user_id}", response_model=ApiResponse, summary="Deactivate user")
async def deactivate_user(
    user_id: str,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Deactivate a user (soft delete) and revoke all their API keys."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    await service.deactivate_user(user_id=user_id, requesting_user=_role)

    return ApiResponse(
        success=True,
        data={"message": "User deactivated"},
        metadata={"request_id": request_id},
    )


@router.post("/{user_id}/reset-password", response_model=ApiResponse, summary="Reset user password")
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Admin reset of a user's password."""
    from modules.backend.services.user import UserService

    service = UserService(db)
    await service.admin_reset_password(
        user_id=user_id,
        new_password=body.new_password,
        requesting_user=_role,
    )

    return ApiResponse(
        success=True,
        data={"message": "Password reset"},
        metadata={"request_id": request_id},
    )


@router.post("/{user_id}/api-keys", response_model=ApiResponse, summary="Create API key for user")
async def create_user_api_key(
    user_id: str,
    body: ApiKeyCreateRequest,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create an API key for any user."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    full_key, api_key = await service.create_api_key(
        user_id=user_id,
        name=body.name,
        expires_in_days=body.expires_in_days,
        requesting_user=_role,
    )

    return ApiResponse(
        success=True,
        data=build_api_key_create_response(full_key, api_key).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.get("/{user_id}/api-keys", response_model=ApiResponse, summary="List user's API keys")
async def list_user_api_keys(
    user_id: str,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """List all API keys for any user."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    keys = await service.list_api_keys(user_id=user_id, requesting_user=_role)

    return ApiResponse(
        success=True,
        data=[ApiKeyResponse.model_validate(k).model_dump(mode="json") for k in keys],
        metadata={"request_id": request_id},
    )


@router.delete("/{user_id}/api-keys/{key_id}", response_model=ApiResponse, summary="Revoke user's API key")
async def revoke_user_api_key(
    user_id: str,
    key_id: str,
    _role: AdminRole,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Revoke an API key for any user."""
    from modules.backend.services.auth import AuthService

    service = AuthService(db)
    await service.revoke_api_key(key_id=key_id, requesting_user=_role)

    return ApiResponse(
        success=True,
        data={"message": "API key revoked"},
        metadata={"request_id": request_id},
    )


