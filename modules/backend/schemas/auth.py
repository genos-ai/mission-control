"""
Auth Schemas.

Request/response schemas for authentication endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from modules.backend.schemas.user import UserResponse


class LoginRequest(BaseModel):
    """Email/password login."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """JWT token pair with user info."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenRefreshRequest(BaseModel):
    """Refresh token exchange."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class TokenRefreshResponse(BaseModel):
    """New JWT token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    """Create a new API key."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: int | None = Field(None, ge=1, le=365)


class ApiKeyCreateResponse(BaseModel):
    """API key creation result. The `key` field is shown ONCE."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key: str
    key_prefix: str
    expires_at: datetime | None = None
    created_at: datetime


class ApiKeyResponse(BaseModel):
    """API key info (without the full key)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


def build_api_key_create_response(full_key: str, api_key: object) -> "ApiKeyCreateResponse":
    """Build an ApiKeyCreateResponse from a full key and ORM ApiKey object.

    Shared by both auth and admin_users endpoints to avoid duplication.
    """
    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=full_key,
        key_prefix=api_key.key_prefix,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


class SseTokenResponse(BaseModel):
    """Short-lived SSE token."""

    token: str
    expires_in: int = 30


class ChangePasswordRequest(BaseModel):
    """Change own password."""

    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)


class ResetPasswordRequest(BaseModel):
    """Admin reset of another user's password."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(..., min_length=12)
