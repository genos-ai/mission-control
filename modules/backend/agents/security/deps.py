"""WASA security agent dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from modules.backend.agents.deps.base import BaseAgentDeps

if TYPE_CHECKING:
    from modules.backend.agents.security.tool_registry import SecurityToolRegistry
    from modules.backend.core.config_schema import SecurityAssessmentSchema


@dataclass
class ScanDeps(BaseAgentDeps):
    """Deps for WASA scanner agent — adds security tool registry and evidence path."""

    tool_registry: "SecurityToolRegistry | None" = None
    security_config: "SecurityAssessmentSchema | None" = None
    evidence_path: str = "@workspace/evidence"
