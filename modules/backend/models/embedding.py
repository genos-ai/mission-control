"""
Generic Embedding Model.

One table for all embeddings across the platform. Keyed by
(source_table, source_id, version). One HNSW index covers all
embeddable types for efficient cross-type unified retrieval.

Cascade: ``mission_id`` (denormalised) references ``missions.id``
with ON DELETE CASCADE so orphan embeddings are cleaned when a
mission is deleted.
"""

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.core.utils import utc_now
from modules.backend.models.base import Base, UUIDMixin


class Embedding(UUIDMixin, Base):
    """A single embedding vector for a source row.

    Source identification:
        - ``source_table``: the origin table name (e.g. 'mission_learnings')
        - ``source_id``: the UUID PK in that table
        - ``version``: embedding model version (bumps trigger backfill)

    The ``embedding`` column type depends on the database dialect:
        - Postgres: ``vector(N)`` via pgvector
        - SQLite: not created (tests skip semantic search)

    The column is defined in the migration, not here, because
    ``pgvector.sqlalchemy.Vector`` is Postgres-only. The model
    uses a plain Text column as a placeholder for SQLAlchemy
    metadata — the migration overrides it with the correct type.
    """

    __tablename__ = "embeddings"

    source_table: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    source_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False), nullable=False,
    )
    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Embedding vector — stored as text in the ORM model.
    # The Alembic migration creates this as vector(1536) on Postgres.
    # Application code uses EmbeddingRepository for all vector operations.
    embedding_data: Mapped[str | None] = mapped_column(
        String, nullable=True,
    )

    model: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    created_at: Mapped[str] = mapped_column(
        DateTime, nullable=False, default=utc_now,
    )

    __table_args__ = (
        UniqueConstraint(
            "source_table", "source_id", "version",
            name="uq_embeddings_source_version",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Embedding(source={self.source_table}:{self.source_id}, "
            f"model={self.model}, version={self.version})>"
        )
