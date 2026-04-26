"""
Prompt Version Model.

Audit trail for every prompt edit. Tracks system prompt changes
(on agent_catalog) and user prompt changes (on mission_team_members).
Each edit creates a new row with a monotonically increasing version number.
"""

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class PromptVersion(UUIDMixin, TimestampMixin, Base):
    """A single version snapshot of a prompt."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index(
            "ix_prompt_versions_entity_lookup",
            "entity_type", "entity_id", "version",
        ),
    )

    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="agent_catalog or mission_team_member",
    )
    entity_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), nullable=False,
        comment="UUID of the owning entity (polymorphic FK)",
    )
    prompt_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="system or user",
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    changed_by: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    change_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    @property
    def content_length(self) -> int:
        """Length of the prompt content."""
        return len(self.content) if self.content else 0

    def __repr__(self) -> str:
        return (
            f"<PromptVersion(entity={self.entity_type}:{self.entity_id}, "
            f"type={self.prompt_type}, v={self.version})>"
        )
