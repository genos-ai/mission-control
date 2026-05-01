"""Tests for the Planning Agent — agent factory and mode selection."""

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from modules.backend.agents.mission.planning.agent import create_agent


class TestCreateAgent:
    def test_dispatch_mode_returns_agent(self):
        agent = create_agent(TestModel())
        assert isinstance(agent, Agent)

    def test_dispatch_mode_has_no_function_tools(self):
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert len(tool_names) == 0, f"Dispatch mode should have no tools, got: {tool_names}"

    def test_chat_mode_returns_agent(self):
        agent = create_agent(TestModel(), chat_mode=True)
        assert isinstance(agent, Agent)

    def test_chat_mode_registers_all_tools(self):
        agent = create_agent(TestModel(), chat_mode=True)
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected = {"get_current_plan", "get_roster", "get_mission_info", "save_plan"}
        assert expected == tool_names, f"Missing tools: {expected - tool_names}"

    def test_dispatch_and_chat_are_independent(self):
        """Creating agents in both modes must not share state."""
        dispatch = create_agent(TestModel())
        chat = create_agent(TestModel(), chat_mode=True)
        dispatch_tools = {t.name for t in dispatch._function_toolset.tools.values()}
        chat_tools = {t.name for t in chat._function_toolset.tools.values()}
        assert len(dispatch_tools) == 0
        assert len(chat_tools) == 4
