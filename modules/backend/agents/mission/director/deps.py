"""
Mission Director Agent Dependencies.

Inherits mission_id and db_session from BaseAgentDeps.
"""

from dataclasses import dataclass

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class MissionDirectorDeps(BaseAgentDeps):
    """Dependencies injected into the Mission Director at runtime."""
