"""
Tool Registry (Plan 65 Phase 1).

Auto-discovers tool modules in modules/backend/tools/ and registers
them on PydanticAI agents at creation time. Each tool module exports
a TOOL_DEF dict and a register(agent) function.

Usage:
    from modules.backend.tools.registry import get_tool_registry

    registry = get_tool_registry()
    registry.register_on_agent(agent, ["search_web", "fetch_url"])
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """Loads tool modules from modules/backend/tools/ and registers them on agents."""

    _instance: ToolRegistry | None = None

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._discover()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    def _discover(self) -> None:
        """Auto-discover tool modules that export TOOL_DEF."""
        import modules.backend.tools as tools_pkg

        for importer, mod_name, is_pkg in pkgutil.iter_modules(tools_pkg.__path__):
            if mod_name.startswith("_") or mod_name == "registry":
                continue

            try:
                mod = importlib.import_module(f"modules.backend.tools.{mod_name}")
                tool_def = getattr(mod, "TOOL_DEF", None)
                if tool_def is None:
                    continue

                name = tool_def.get("name", mod_name)
                self._tools[name] = {
                    "name": name,
                    "description": tool_def.get("description", ""),
                    "category": tool_def.get("category", ""),
                    "deps": tool_def.get("deps", []),
                    "module": mod,
                }
                logger.debug(
                    "Tool registered",
                    extra={"tool": name, "category": tool_def.get("category", "")},
                )

            except Exception as exc:
                logger.warning(
                    "Failed to load tool module",
                    extra={"module": mod_name, "error": str(exc)},
                )

        logger.info(
            "Tool registry initialized",
            extra={"tool_count": len(self._tools)},
        )

    def get(self, name: str) -> dict[str, Any]:
        """Get tool metadata by name. Raises KeyError if not found."""
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_all(self) -> list[dict[str, Any]]:
        """List all registered tools with metadata."""
        return [
            {"name": t["name"], "description": t["description"], "category": t["category"]}
            for t in sorted(self._tools.values(), key=lambda t: t["name"])
        ]

    def register_on_agent(self, agent: Any, tool_names: list[str]) -> list[str]:
        """Register tools on a PydanticAI agent. Returns names registered.

        Silently skips unknown tool names — the tools list may contain
        agent-specific adapter tools that the registry doesn't manage.
        """
        registered = []
        for name in tool_names:
            if name not in self._tools:
                continue
            mod = self._tools[name]["module"]
            register_fn = getattr(mod, "register", None)
            if register_fn is None:
                logger.warning("Tool has no register()", extra={"tool": name})
                continue
            register_fn(agent)
            registered.append(name)
        return registered


def get_tool_registry() -> ToolRegistry:
    """Get the global ToolRegistry singleton."""
    return ToolRegistry.get_instance()
