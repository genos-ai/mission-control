"""Tests for the Workflow Architect agent creation and configuration."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.backend.agents.mission.workflow.architect.deps import ArchitectAgentDeps


class TestCreateAgent:
    """Tests for agent factory function."""

    @patch("modules.backend.agents.mission.workflow.architect.agent.Agent")
    @patch("modules.backend.agents.mission.workflow.architect.agent.assemble_instructions")
    def test_creates_agent_with_model_object(self, mock_assemble, mock_agent_cls):
        from modules.backend.agents.mission.workflow.architect.agent import create_agent

        mock_assemble.return_value = "You are the architect."
        mock_model = MagicMock()
        mock_agent_cls.return_value = MagicMock()

        agent = create_agent(mock_model)

        assert agent is not None

    @patch("modules.backend.agents.mission.workflow.architect.agent.Agent")
    @patch("modules.backend.agents.mission.workflow.architect.agent.assemble_instructions")
    def test_assembles_instructions_for_correct_category(self, mock_assemble, mock_agent_cls):
        from modules.backend.agents.mission.workflow.architect.agent import create_agent

        mock_assemble.return_value = "system prompt"
        mock_model = MagicMock()
        mock_agent_cls.return_value = MagicMock()

        create_agent(mock_model)

        mock_assemble.assert_called_once_with("mission.workflow.architect")


class TestArchitectAgentDeps:
    """Tests for ArchitectAgentDeps dataclass."""

    def test_default_values(self):
        deps = ArchitectAgentDeps(
            project_root=Path("/tmp"),
            scope=MagicMock(),
        )
        assert deps.mission_id is None
        assert deps.mission_brief == ""
        assert deps.team_summary == ""
        assert deps.db_session is None
        assert deps.session_id is None
        assert deps.on_event is None

    def test_custom_values(self):
        mock_session = MagicMock()
        deps = ArchitectAgentDeps(
            project_root=Path("/project"),
            scope=MagicMock(),
            mission_id="m-123",
            mission_brief="Build a code review pipeline",
            team_summary="- code.qa.agent: reviews code",
            db_session=mock_session,
            session_id="f5fc1ba9-4d30-5ecd-a688-783a3909be84",
        )
        assert deps.mission_id == "m-123"
        assert deps.mission_brief == "Build a code review pipeline"
        assert deps.db_session is mock_session
        assert deps.session_id == "f5fc1ba9-4d30-5ecd-a688-783a3909be84"
