"""
Research agent dependencies (Plan 40 §1).

ResearchAgentDeps extends BaseAgentDeps with an httpx client for
web search and content extraction. Used by the searcher agent;
other research agents (strategist, analyst, synthesizer, verifier)
use BaseAgentDeps since they have no tools.
"""

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from modules.backend.agents.deps.base import BaseAgentDeps, FileScope


@dataclass
class ResearchAgentDeps(BaseAgentDeps):
    """Dependencies for research agents that need HTTP access."""

    http_client: httpx.AsyncClient | None = None
