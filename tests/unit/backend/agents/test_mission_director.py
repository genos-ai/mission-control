"""
Mission Director agent tests.

Tests agent factory, tool registration, and deps dataclass.
Uses PydanticAI TestModel — no real API calls.
"""

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from modules.backend.agents.deps.base import FileScope
from modules.backend.agents.horizontal.mission_director.agent import create_agent
from modules.backend.agents.horizontal.mission_director.deps import MissionDirectorDeps
from modules.backend.core.config import find_project_root


class TestMissionDirectorAgent:
    """Tests for the Mission Director agent factory."""

    def test_create_agent_returns_agent(self):
        """create_agent should return a PydanticAI Agent."""
        agent = create_agent(TestModel())
        assert isinstance(agent, Agent)

    def test_agent_has_read_tools(self):
        """Agent should have all read tools registered."""
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected_read_tools = {
            "get_mission_info",
            "list_team",
            "get_execution_history",
            "get_execution_detail",
            "get_mission_context",
            "list_workflows",
        }
        assert expected_read_tools.issubset(tool_names), (
            f"Missing read tools: {expected_read_tools - tool_names}"
        )

    def test_agent_has_action_tools(self):
        """Agent should have action tools registered."""
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        expected_action_tools = {
            "run_objective",
            "run_workflow",
        }
        assert expected_action_tools.issubset(tool_names), (
            f"Missing action tools: {expected_action_tools - tool_names}"
        )

    def test_agent_tool_count(self):
        """Agent should have exactly 8 tools (6 read + 2 action)."""
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert len(tool_names) == 8, f"Expected 8 tools, got {len(tool_names)}: {tool_names}"

    def test_gate_tools_not_registered(self):
        """Gate tools should NOT be registered (deferred to Phase 2)."""
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "approve_gate" not in tool_names
        assert "reject_gate" not in tool_names
        assert "get_pending_gates" not in tool_names


class TestMissionDirectorDeps:
    """Tests for the MissionDirectorDeps dataclass."""

    def test_deps_defaults(self):
        """Deps should have sensible defaults."""
        deps = MissionDirectorDeps(
            project_root=find_project_root(),
            scope=FileScope(read_paths=[], write_paths=[]),
        )
        assert deps.mission_id == ""
        assert deps.db_session is None
        assert deps.session_id is None

    def test_deps_with_values(self):
        """Deps should store provided values."""
        deps = MissionDirectorDeps(
            project_root=find_project_root(),
            scope=FileScope(read_paths=["config/"], write_paths=[]),
            mission_id="test-mission-id",
            db_session="fake-session",
            session_id="test-session",
        )
        assert deps.mission_id == "test-mission-id"
        assert deps.db_session == "fake-session"
        assert deps.session_id == "test-session"
