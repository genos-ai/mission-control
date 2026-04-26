"""
SQLAlchemy Base Model.

Base class for all database models with common fields and utilities.
"""

from datetime import datetime
from uuid import uuid5, uuid7, UUID

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from modules.backend.core.utils import utc_now


# ── System account UUIDs ──────────────────────────────────
# Deterministic UUID v5 from a fixed namespace. Same value in every
# environment (dev, staging, prod). Used as users.id for service
# accounts that own automated missions, workflows, and schedules.

SYSTEM_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

SYSTEM_CLI_ID = str(uuid5(SYSTEM_NAMESPACE, "system:cli"))
SYSTEM_WORKFLOW_ID = str(uuid5(SYSTEM_NAMESPACE, "system:workflow"))
SYSTEM_SCHEDULER_ID = str(uuid5(SYSTEM_NAMESPACE, "system:scheduler"))

SYSTEM_ACCOUNTS = {
    SYSTEM_CLI_ID: {"display_name": "CLI Runner", "system_role": "user"},
    SYSTEM_WORKFLOW_ID: {"display_name": "Workflow Runner", "system_role": "user"},
    SYSTEM_SCHEDULER_ID: {"display_name": "Scheduler", "system_role": "user"},
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class UUIDMixin:
    """Mixin that adds a UUID primary key (native PostgreSQL UUID type)."""

    id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid7()),
    )


# Example model combining mixins:
#
# class User(UUIDMixin, TimestampMixin, Base):
#     __tablename__ = "users"
#
#     email: Mapped[str] = mapped_column(unique=True, nullable=False)
#     hashed_password: Mapped[str] = mapped_column(nullable=False)
