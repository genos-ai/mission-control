"""
Mission Supervisor Agent Dependencies (Plan 51 Phase D).

Mirrors MissionDirectorDeps — mission_id + db_session. Kept
separate so supervisor-specific fields can be added later without
affecting the Director.
"""

from dataclasses import dataclass
from typing import Any

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class MissionSupervisorDeps(BaseAgentDeps):
    """Dependencies injected into the Mission Supervisor at runtime."""

    mission_id: str = ""
    db_session: Any = None  # AsyncSession — required for service access
