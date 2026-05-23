"""
Workflow Architect Agent Dependencies.

Inherits mission_id and db_session from BaseAgentDeps.
Adds mission_brief and team_summary for design context.
"""

from dataclasses import dataclass

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class ArchitectAgentDeps(BaseAgentDeps):
    """Dependencies injected into the Workflow Architect at runtime."""

    mission_brief: str = ""
    team_summary: str = ""
