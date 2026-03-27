"""
Mission Director Agent Dependencies.

Custom deps providing database session and mission_id for service
access. The db_session is injected at invocation time via the
handle() call chain.
"""

from dataclasses import dataclass
from typing import Any

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class MissionDirectorDeps(BaseAgentDeps):
    """Dependencies injected into the Mission Director at runtime."""

    mission_id: str = ""
    db_session: Any = None  # AsyncSession — required for service access
