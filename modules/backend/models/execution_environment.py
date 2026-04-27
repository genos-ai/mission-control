"""
Execution Environment Model.

Tracks active execution environments (containers, worktrees) so they
persist across multiple executions within a mission and can be cleaned
up on mission archive/delete or idle timeout.
"""

import enum

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class EnvironmentStatus(str, enum.Enum):
    """Execution environment lifecycle status."""

    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    DESTROYED = "destroyed"


class ExecutionEnvironmentModel(UUIDMixin, TimestampMixin, Base):
    """Tracks a persistent execution environment (container or worktree)."""

    __tablename__ = "execution_environments"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="Environment mode: container, worktree",
    )
    status: Mapped[str] = mapped_column(
        Enum(EnvironmentStatus, native_enum=False),
        default=EnvironmentStatus.CREATING,
        nullable=False,
    )
    container_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Docker container ID (for container mode)",
    )
    container_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Docker container name",
    )
    branch_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    working_dir: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    image: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    execution_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    last_execution_at: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="ISO timestamp of last execution in this environment",
    )
    config: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Backend-specific configuration used to create this environment",
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionEnvironment(id={self.id}, mission={self.mission_id}, "
            f"mode={self.mode}, status={self.status})>"
        )
