"""
Database Admin Service.

Encapsulates database inspection and cleanup operations for CLI/admin use.
All raw SQL lives here — clients never execute queries directly.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Infrastructure tables — preserved by default (missions + PCD + users)
PROJECT_TABLES = [
    "milestone_summaries",
    "mission_decisions",
    "context_changes",
    "mission_contexts",
    "mission_members",
    "missions",
    "api_keys",
    "users",
    "workflow_schedules",
]

# Run data tables — cleared by db clear (dependency order: children first)
RUN_TABLES = [
    "task_dependencies",
    "execution_decisions",
    "task_attempts",
    "task_executions",
    "execution_records",
    "tasks",
    "session_messages",
    "session_channels",
    "workflow_runs",
    "sessions",
]

# Execution-only tables
EXECUTION_TABLES = [
    "task_dependencies",
    "execution_decisions",
    "task_attempts",
    "task_executions",
    "execution_records",
    "tasks",
    "workflow_runs",
]

# Task-only tables (Plan 72)
TASK_TABLES = [
    "task_dependencies",
    "tasks",
]

# Session-only tables
SESSION_TABLES = [
    "session_messages",
    "session_channels",
    "sessions",
]

# All tables in dependency order (children first for safe truncation)
ALL_TABLES = RUN_TABLES + PROJECT_TABLES


class DatabaseAdminService:
    """Database inspection and cleanup for admin/CLI use."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["DatabaseAdminService", None]:
        """Create a DatabaseAdminService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield DatabaseAdminService(db)

    async def get_table_row_counts(self) -> list[tuple[str, int]]:
        """Return (table_name, row_count) for all application tables."""
        counts = []
        for tbl in ALL_TABLES:
            result = await self._session.execute(text(f"SELECT COUNT(*) FROM {tbl}"))  # noqa: S608
            counts.append((tbl, result.scalar()))
        return counts

    async def get_table_columns(self, table: str) -> list[tuple[str, str, str]]:
        """Return (column_name, data_type, is_nullable) for a table."""
        self._validate_table(table)
        result = await self._session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"table": table},
        )
        return result.fetchall()

    async def get_table_row_count(self, table: str) -> int:
        """Return row count for a single table."""
        self._validate_table(table)
        result = await self._session.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
        return result.scalar()

    async def query_recent_rows(
        self,
        table: str,
        limit: int = 20,
    ) -> tuple[list[str], list[Any]]:
        """Query recent rows from a table.

        Returns:
            Tuple of (column_names, rows).
        """
        self._validate_table(table)

        col_result = await self._session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table ORDER BY ordinal_position"
            ),
            {"table": table},
        )
        columns = [row[0] for row in col_result.fetchall()]

        order_col = "created_at" if "created_at" in columns else columns[0]
        result = await self._session.execute(
            text(f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT :limit"),  # noqa: S608
            {"limit": limit},
        )

        return columns, result.fetchall()

    async def truncate_tables(self, tables: list[str]) -> int:
        """Truncate the given tables with CASCADE. Returns count of tables truncated."""
        for tbl in tables:
            self._validate_table(tbl)
            await self._session.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))  # noqa: S608
        await self._session.commit()

        logger.info("Tables truncated", extra={"tables": tables, "count": len(tables)})
        return len(tables)

    @staticmethod
    def _validate_table(table: str) -> None:
        """Ensure the table name is in the known set (prevents SQL injection)."""
        if table not in ALL_TABLES:
            raise ValueError(f"Unknown table: {table}. Valid: {', '.join(ALL_TABLES)}")
