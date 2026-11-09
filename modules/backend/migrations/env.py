"""
Alembic Migration Environment.

Configures Alembic to work with our async SQLAlchemy setup.
Loads database URL from config/.env and imports all models
for autogenerate support.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Phase 2: New tables
from modules.backend.models.agent_catalog import AgentCatalog  # noqa: F401
from modules.backend.models.api_key import ApiKey  # noqa: F401

# Import Base metadata and all models for autogenerate
from modules.backend.models.base import Base

# Phase 4+: Plan, artifacts, knowledge, LLM tracking, embeddings
from modules.backend.models.embedding import Embedding  # noqa: F401
from modules.backend.models.execution_environment import ExecutionEnvironmentModel  # noqa: F401
from modules.backend.models.execution_record import (  # noqa: F401
    ExecutionDecision,
    ExecutionRecord,
    TaskAttempt,
    TaskExecution,
)
from modules.backend.models.llm_call import LlmCall  # noqa: F401
from modules.backend.models.mission import Mission, MissionMember  # noqa: F401
from modules.backend.models.mission_artifact import MissionArtifact  # noqa: F401
from modules.backend.models.mission_context import ContextChange, MissionContext  # noqa: F401
from modules.backend.models.mission_history import MilestoneSummary, MissionDecision  # noqa: F401
from modules.backend.models.mission_intent import MissionIntent  # noqa: F401
from modules.backend.models.mission_learning import MissionLearning  # noqa: F401
from modules.backend.models.mission_plan import MissionPlan  # noqa: F401
from modules.backend.models.mission_run import MissionRun  # noqa: F401
from modules.backend.models.mission_run_digest import MissionRunDigest  # noqa: F401
from modules.backend.models.mission_team import MissionTeamMember  # noqa: F401
from modules.backend.models.model_pricing import ModelPricing  # noqa: F401
from modules.backend.models.prompt_version import PromptVersion  # noqa: F401
from modules.backend.models.revoked_session import RevokedSession  # noqa: F401
from modules.backend.models.session import Session, SessionChannel, SessionMessage  # noqa: F401
from modules.backend.models.session_followup import SessionFollowup  # noqa: F401
from modules.backend.models.task import Task, TaskDependency  # noqa: F401

# Phase 3: Users and API keys
from modules.backend.models.user import User  # noqa: F401
from modules.backend.models.workflow_definition import WorkflowDefinition  # noqa: F401

# Import all models here so Alembic can detect them
# Add new model imports as you create them
from modules.backend.models.workflow_run import WorkflowRun  # noqa: F401
from modules.backend.models.workflow_schedule import WorkflowSchedule  # noqa: F401

# Alembic Config object
config = context.config

# Setup logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def get_database_url() -> str:
    """Get database URL from YAML config and secrets."""
    from modules.backend.core.config import get_database_url as _get_database_url

    return _get_database_url()


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    Useful for reviewing migrations before applying.

    Usage:
        alembic upgrade head --sql
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with the given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async engine.

    Creates an async engine, connects, and runs migrations.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


# Determine which mode to run
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
