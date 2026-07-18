"""Tests for the Planning Agent — agent factory and mode selection."""

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from modules.backend.agents.mission.planning.agent import create_agent

# The 8 planning tools (shared between dispatch and chat modes)
PLANNING_TOOLS = {
    "add_task",
    "update_task",
    "remove_task",
    "set_upstream_input",
    "set_static_input",
    "set_file_manifest",
    "set_verification",
    "finalise_plan",
}

# Read-only introspection tools (chat mode only)
READ_TOOLS = {"get_current_plan", "get_roster", "get_mission_info"}


class TestCreateAgent:
    def test_dispatch_mode_returns_agent(self):
        agent = create_agent(TestModel())
        assert isinstance(agent, Agent)

    def test_dispatch_mode_has_planning_tools(self):
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert PLANNING_TOOLS == tool_names, f"Expected {PLANNING_TOOLS}, got {tool_names}"

    def test_chat_mode_returns_agent(self):
        agent = create_agent(TestModel(), chat_mode=True)
        assert isinstance(agent, Agent)

    def test_chat_mode_has_planning_and_read_tools(self):
        agent = create_agent(TestModel(), chat_mode=True)
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected = PLANNING_TOOLS | READ_TOOLS
        assert (
            expected == tool_names
        ), f"Missing: {expected - tool_names}, Extra: {tool_names - expected}"

    def test_dispatch_and_chat_are_independent(self):
        """Creating agents in both modes must not share state."""
        dispatch = create_agent(TestModel())
        chat = create_agent(TestModel(), chat_mode=True)
        dispatch_tools = {t.name for t in dispatch._function_toolset.tools.values()}
        chat_tools = {t.name for t in chat._function_toolset.tools.values()}
        assert dispatch_tools == PLANNING_TOOLS
        assert chat_tools == PLANNING_TOOLS | READ_TOOLS
