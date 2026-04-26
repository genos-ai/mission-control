"""Mission Control shared helpers — re-exports from submodules.

Split from helpers.py into:
  model_builder.py  — model construction and settings
  prompt_builder.py — layered prompts and planning prompts
  agent_setup.py    — deps, usage limits, module imports
  routing.py        — agent routing and fallback
  event_emitter.py  — event publishing and message persistence
  agent_executor.py — execute_agent closure and planning agent caller
"""

from modules.backend.core.model_builder import (
    _build_model,
    _get_model_name,
    build_model_settings,
)
from modules.backend.agents.mission_control.helpers.prompt_builder import (
    _append_validation_feedback,
    _build_planning_prompt,
    _build_roster_prompt,
    assemble_instructions,
    load_agent_system_prompt,
)
from modules.backend.agents.mission_control.helpers.agent_setup import (
    _build_agent_deps,
    _get_usage_limits,
    _import_agent_module,
    build_deps_from_config,
)
from modules.backend.agents.mission_control.helpers.routing import (
    _resolve_agent,
    get_chat_agent,
)
from modules.backend.agents.mission_control.helpers.event_emitter import (
    _emit,
    _emit_tool_events,
    _persist_messages,
    _publish,
)
from modules.backend.agents.mission_control.helpers.agent_executor import (
    _call_planning_agent,
    _make_agent_executor,
)

__all__ = [
    "_append_validation_feedback",
    "_build_agent_deps",
    "_build_model",
    "_build_planning_prompt",
    "_build_roster_prompt",
    "_call_planning_agent",
    "_emit",
    "_emit_tool_events",
    "_get_model_name",
    "_get_usage_limits",
    "_import_agent_module",
    "_make_agent_executor",
    "_persist_messages",
    "_publish",
    "_resolve_agent",
    "assemble_instructions",
    "build_deps_from_config",
    "build_model_settings",
    "get_chat_agent",
    "load_agent_system_prompt",
]
