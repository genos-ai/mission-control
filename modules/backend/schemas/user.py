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
    current_mission_id: str | None = None
    current_mission_name: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: object) -> "UserResponse":
        """Build response with denormalized current_mission_name."""
        mission = getattr(user, "current_mission", None)
        # Build via dict to avoid reading non-existent attrs from ORM objects
        data = {
            f: getattr(user, f)
            for f in cls.model_fields
            if f != "current_mission_name" and hasattr(user, f)
        }
        data["current_mission_name"] = mission.name if mission else None
        return cls.model_validate(data)


class UserBriefResponse(BaseModel):
    """Minimal user info for embedding in other responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    system_role: str
    is_service_account: bool


class UpdateProfileRequest(BaseModel):
    """Schema for self-service profile update (non-admin)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=200)


class SetCurrentMissionRequest(BaseModel):
    """Schema for setting the user's current mission."""

    model_config = ConfigDict(extra="forbid")

    mission_id: str | None = Field(
        None,
        description="Mission ID to select, or null to clear selection",
    )
