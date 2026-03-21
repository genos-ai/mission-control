"""
Workflow Architect Agent Dependencies.

Custom deps providing database session access for catalog browsing,
workflow validation, and persistence. The db_session is injected at
invocation time by the architect service.
"""

from dataclasses import dataclass, field
from typing import Any

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class ArchitectAgentDeps(BaseAgentDeps):
    """Dependencies injected into the Workflow Architect at runtime."""

    mission_id: str = ""
    mission_brief: str = ""
    team_summary: str = ""
    db_session: Any = None
