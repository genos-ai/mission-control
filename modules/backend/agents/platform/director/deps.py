"""
Platform Director Agent Dependencies.

Similar to MissionDirectorDeps but with unscoped access —
can query across all missions and platform internals.
"""

from dataclasses import dataclass
from typing import Any

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class PlatformDirectorDeps(BaseAgentDeps):
    """Dependencies injected into the Platform Director at runtime."""

    db_session: Any = None  # AsyncSession — required for service access
