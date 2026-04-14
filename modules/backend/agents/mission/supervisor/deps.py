"""
Mission Supervisor Agent Dependencies (Plan 51 Phase D).

Inherits mission_id and db_session from BaseAgentDeps.
Overrides project_root and scope with safe read-only defaults.
"""

from dataclasses import dataclass, field
from pathlib import Path

from modules.backend.agents.deps.base import BaseAgentDeps, FileScope


@dataclass
class MissionSupervisorDeps(BaseAgentDeps):
    """Dependencies injected into the Mission Supervisor at runtime.

    The supervisor is a read-only agent — it reads plan state and
    audit trail but never writes files. project_root and scope
    default to safe read-only values so the reviewer can construct
    deps without a full config lookup.
    """

    project_root: Path = field(default_factory=lambda: Path("."))
    scope: FileScope = field(default_factory=lambda: FileScope(read_paths=["docs/"], write_paths=[]))
