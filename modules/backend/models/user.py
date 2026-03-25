"""
User Model.

Persistent user identity for authentication and authorization.
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class SystemRole(str, enum.Enum):
    """System-wide role for authorization."""

    VIEWER = "viewer"
    USER = "user"
    ADMIN = "admin"


class User(UUIDMixin, TimestampMixin, Base):
    """A platform user with authentication credentials and role."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    hashed_password: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    system_role: Mapped[str] = mapped_column(
        String(20), default=SystemRole.USER.value, nullable=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    is_service_account: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    current_mission_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan",
    )
    current_mission: Mapped["Mission | None"] = relationship(
        "Mission",
        foreign_keys=[current_mission_id],
        lazy="joined",
    )

    def has_role(self, minimum: str) -> bool:
        """Check if this user's role meets the minimum required level.

        Reads role levels from security.yaml config — does NOT hardcode
        a static level map.

        Raises:
            ValueError: If minimum is not a recognized role name.
        """
        from modules.backend.core.security import check_role_level

        return check_role_level(self.system_role, minimum)

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, email={self.email!r}, "
            f"role={self.system_role})>"
        )
