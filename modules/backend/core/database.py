"""
Database Configuration.

SQLAlchemy async engine and session management.
Uses lazy initialization to prevent import-time failures when .env is not configured.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Module-level state for lazy initialization
_engine: Any = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine() -> Any:
    """Create async SQLAlchemy engine."""
    from modules.backend.core.config import get_app_config, get_database_url

    db_config = get_app_config().database

    engine = create_async_engine(
        get_database_url(),
        pool_size=db_config.pool_size,
        max_overflow=db_config.max_overflow,
        pool_timeout=db_config.pool_timeout,
        pool_recycle=db_config.pool_recycle,
        echo=db_config.echo,
    )
    logger.debug("Database engine created", extra={"host": db_config.host})
    return engine


def get_engine() -> Any:
    """
    Get the database engine, creating it on first use.

    Returns:
        SQLAlchemy async engine instance

    Raises:
        RuntimeError: If database configuration is invalid
    """
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get the session factory, creating it on first use.

    Returns:
        SQLAlchemy async session factory
    """
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Standalone async session context manager for non-FastAPI callers.

    Usage (Temporal Activities, CLI scripts, background tasks):
        async with get_async_session() as db:
            service = SomeService(db)
            await service.do_work()
            await db.commit()

    Unlike get_db_session(), this does NOT auto-commit. The caller
    controls the transaction boundary explicitly.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except SQLAlchemyError:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.

    Usage in endpoints:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Sync session (for registry bootstrap — one-time blocking load)
# ---------------------------------------------------------------------------

_sync_engine: Any = None


@contextmanager
def get_sync_session():
    """Synchronous DB session for startup-time loading (e.g. agent registry).

    Uses a separate sync engine. Only use for one-time bootstrap queries —
    all runtime DB access should use the async session.
    """
    global _sync_engine
    if _sync_engine is None:
        from modules.backend.core.config import get_database_url

        _sync_engine = _create_sync_engine(
            get_database_url(async_driver=False),
            pool_pre_ping=True,
        )
    factory = sessionmaker(bind=_sync_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
