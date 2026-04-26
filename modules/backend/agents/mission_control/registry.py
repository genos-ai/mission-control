"""DEPRECATED: Import from modules.backend.core.agent_registry instead.

Re-exports for backward compatibility.
"""

from modules.backend.core.agent_registry import (  # noqa: F401
    AgentRegistry,
    get_registry,
)

__all__ = ["AgentRegistry", "get_registry"]
