"""
Platform Director Agent Dependencies.

Inherits mission_id and db_session from BaseAgentDeps.
Unscoped access — can query across all missions and platform internals.
"""

from dataclasses import dataclass

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class PlatformDirectorDeps(BaseAgentDeps):
    """Dependencies injected into the Platform Director at runtime."""
