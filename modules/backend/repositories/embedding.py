"""
Embedding Repository.

Single owner of all vector operations. Provides semantic search,
hybrid search, and embedding management across all embeddable types.

Uses raw SQL for pgvector operations (``<=>`` cosine distance)
because SQLAlchemy's ORM doesn't natively support vector types.
Structured queries go through the ORM as usual.
"""

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.embedding import Embedding
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class EmbeddingRepository(BaseRepository[Embedding]):
    """Repository for the generic embeddings table.

    Vector queries use raw SQL for ``<=>`` operator access.
    All other operations use the ORM via BaseRepository.
    """

    model = Embedding

    async def upsert(
        self,
        source_table: str,
        source_id: str,
        embedding: list[float],
        model: str,
        version: int,
        *,
        mission_id: str | None = None,
        content_hash: str | None = None,
    ) -> Embedding:
        """Insert or update an embedding for a source row.

        Uses the unique constraint on (source_table, source_id, version)
        to determine insert vs update.
        """
        result = await self.session.execute(
            select(Embedding)
            .where(Embedding.source_table == source_table)
            .where(Embedding.source_id == source_id)
            .where(Embedding.version == version)
        )
        existing = result.scalar_one_or_none()

        vector_str = _to_pgvector_literal(embedding)

        if existing:
            # Update in place
            await self.session.execute(
                text(
                    "UPDATE embeddings SET embedding_data = CAST(:vec AS vector), "
                    "model = :model, content_hash = :hash "
                    "WHERE id = :id"
                ).bindparams(
                    vec=vector_str,
                    model=model,
                    hash=content_hash,
                    id=existing.id,
                )
            )
            return existing
        else:
            # Insert new
            from uuid import uuid4
            from modules.backend.core.utils import utc_now

            new_id = str(uuid4())
            await self.session.execute(
                text(
                    "INSERT INTO embeddings "
                    "(id, source_table, source_id, mission_id, "
                    "embedding_data, model, version, content_hash, created_at) "
                    "VALUES (:id, :src_table, :src_id, :mission_id, "
                    "CAST(:vec AS vector), :model, :version, :hash, :created_at)"
                ).bindparams(
                    id=new_id,
                    src_table=source_table,
                    src_id=source_id,
                    mission_id=mission_id,
                    vec=vector_str,
                    model=model,
                    version=version,
                    hash=content_hash,
                    created_at=utc_now(),
                )
            )
            # Return ORM instance for consistency
            return Embedding(
                id=new_id,
                source_table=source_table,
                source_id=source_id,
                mission_id=mission_id,
                model=model,
                version=version,
                content_hash=content_hash,
            )

    async def get_by_source(
        self,
        source_table: str,
        source_id: str,
        version: int,
    ) -> Embedding | None:
        """Get an embedding by source identity."""
        result = await self.session.execute(
            select(Embedding)
            .where(Embedding.source_table == source_table)
            .where(Embedding.source_id == source_id)
            .where(Embedding.version == version)
        )
        return result.scalar_one_or_none()

    async def semantic_search(
        self,
        query_vec: list[float],
        *,
        source_tables: list[str] | None = None,
        mission_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find nearest embeddings by cosine distance.

        Returns dicts with source_table, source_id, distance.
        Requires pgvector — raises on SQLite.
        """
        vec_literal = _to_pgvector_literal(query_vec)

        where_clauses = []
        params: dict = {"vec": vec_literal, "limit": limit}

        if source_tables:
            placeholders = ", ".join(
                f":st_{i}" for i in range(len(source_tables))
            )
            where_clauses.append(f"source_table IN ({placeholders})")
            for i, st in enumerate(source_tables):
                params[f"st_{i}"] = st

        if mission_id:
            where_clauses.append("mission_id = :mission_id")
            params["mission_id"] = mission_id

        where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = text(
            f"SELECT source_table, source_id, "
            f"embedding_data <=> CAST(:vec AS vector) AS distance "
            f"FROM embeddings "
            f"WHERE embedding_data IS NOT NULL{where_sql} "
            f"ORDER BY embedding_data <=> CAST(:vec AS vector) "
            f"LIMIT :limit"
        ).bindparams(**params)

        result = await self.session.execute(sql)
        rows = result.fetchall()
        return [
            {
                "source_table": row[0],
                "source_id": row[1],
                "distance": float(row[2]),
            }
            for row in rows
        ]

    async def hybrid_search(
        self,
        query_vec: list[float],
        filter_ids: dict[str, list[str]],
        *,
        limit: int = 20,
    ) -> list[dict]:
        """Structured filter → vector rerank.

        Args:
            query_vec: The query embedding vector.
            filter_ids: Mapping of source_table -> list of source_ids
                        from the structured filter step.
            limit: Max results to return.

        Returns:
            Sorted dicts with source_table, source_id, distance.
        """
        if not filter_ids:
            return []

        # Build a flat list of (source_table, source_id) conditions
        or_conditions = []
        params: dict = {"vec": _to_pgvector_literal(query_vec), "limit": limit}
        idx = 0
        for table, ids in filter_ids.items():
            for src_id in ids:
                or_conditions.append(
                    f"(source_table = :t_{idx} AND source_id = :s_{idx})"
                )
                params[f"t_{idx}"] = table
                params[f"s_{idx}"] = src_id
                idx += 1

        if not or_conditions:
            return []

        where_sql = " OR ".join(or_conditions)

        sql = text(
            f"SELECT source_table, source_id, "
            f"embedding_data <=> CAST(:vec AS vector) AS distance "
            f"FROM embeddings "
            f"WHERE embedding_data IS NOT NULL AND ({where_sql}) "
            f"ORDER BY embedding_data <=> CAST(:vec AS vector) "
            f"LIMIT :limit"
        ).bindparams(**params)

        result = await self.session.execute(sql)
        rows = result.fetchall()
        return [
            {
                "source_table": row[0],
                "source_id": row[1],
                "distance": float(row[2]),
            }
            for row in rows
        ]

    async def list_missing(
        self,
        source_table: str,
        current_version: int,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """Find source rows that don't have an embedding at the current version.

        Returns dicts with source_table and source_id so the caller can
        fetch the source row and generate the embedding.

        Uses a LEFT JOIN approach via raw SQL since we need to check
        absence across tables.
        """
        sql = text(
            f"SELECT :src_table AS source_table, t.id AS source_id "
            f"FROM {source_table} t "
            f"LEFT JOIN embeddings e "
            f"  ON e.source_table = :src_table "
            f"  AND e.source_id = t.id "
            f"  AND e.version = :version "
            f"WHERE e.id IS NULL "
            f"LIMIT :limit"
        ).bindparams(
            src_table=source_table,
            version=current_version,
            limit=limit,
        )
        result = await self.session.execute(sql)
        rows = result.fetchall()
        return [
            {"source_table": row[0], "source_id": row[1]}
            for row in rows
        ]

    async def delete_by_source(
        self,
        source_table: str,
        source_id: str,
    ) -> int:
        """Delete all embeddings for a source row. Returns count deleted."""
        result = await self.session.execute(
            delete(Embedding)
            .where(Embedding.source_table == source_table)
            .where(Embedding.source_id == source_id)
        )
        return result.rowcount


def _to_pgvector_literal(vec: list[float]) -> str:
    """Convert a Python list of floats to a pgvector literal string.

    e.g. [1.0, 2.0, 3.0] -> '[1.0,2.0,3.0]'
    """
    return "[" + ",".join(str(f) for f in vec) + "]"
