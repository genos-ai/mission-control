"""Unit tests for planning tools — verify tool registration and delegation."""

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from modules.backend.agents.mission.planning.build_session import PlanBuildingSession
from modules.backend.agents.mission.planning.tools import register_planning_tools
from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)


def _entry(name: str) -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name=name,
        agent_version="1.0.0",
        description=f"Test {name}",
        model=RosterModelSchema(name="test:model"),
        interface=RosterInterfaceSchema(),
        constraints=RosterConstraintsSchema(),
    )


ROSTER = Roster(agents=[
    _entry("security.webapp.scanner.agent"),
    _entry("security.webapp.triage.agent"),
    _entry("security.webapp.reporter.agent"),
])


@dataclass
class FakeDeps:
    build_session: PlanBuildingSession = field(default=None)


class TestToolRegistration:
    def test_registers_all_8_tools(self):
        agent = Agent(TestModel(), deps_type=FakeDeps)
        register_planning_tools(agent)
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected = {
            "add_task", "update_task", "remove_task",
            "set_upstream_input", "set_static_input",
            "set_file_manifest", "set_verification", "finalise_plan",
        }
        assert expected == tool_names, f"Missing: {expected - tool_names}, Extra: {tool_names - expected}"

    def test_no_overlap_with_other_tools(self):
        """Planning tools should not conflict with existing tool names."""
        agent = Agent(TestModel(), deps_type=FakeDeps)
        register_planning_tools(agent)
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        # These are chat-mode introspection tools — should NOT be registered
        assert "get_current_plan" not in tool_names
        assert "get_roster" not in tool_names
        assert "save_plan" not in tool_names


class TestToolDocstrings:
    """Verify all tools have descriptive docstrings (LLM reads them)."""

    def test_all_tools_have_docstrings(self):
        agent = Agent(TestModel(), deps_type=FakeDeps)
        register_planning_tools(agent)
        for tool in agent._function_toolset.tools.values():
            assert tool.description, f"Tool '{tool.name}' has no description"
            assert len(tool.description) > 20, f"Tool '{tool.name}' description too short"
