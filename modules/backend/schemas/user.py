"""
User Schemas.

Request/response schemas for user management endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Schema for creating a user (admin endpoint)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(..., max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    password: str | None = Field(None, min_length=12)
    system_role: str = Field(default="user", pattern=r"^(viewer|user|admin)$")
    is_service_account: bool = False


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=200)
    system_role: str | None = Field(None, pattern=r"^(viewer|user|admin)$")
    is_active: bool | None = None


class UserResponse(BaseModel):
    """Schema for user API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    system_role: str
    is_active: bool
    is_service_account: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserBriefResponse(BaseModel):
    """Minimal user info for embedding in other responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    system_role: str
    is_service_account: bool
