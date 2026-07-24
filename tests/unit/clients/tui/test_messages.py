"""Tests for TUI Textual Message types."""

from modules.clients.tui.messages import (
    AgentSelected,
    MissionCancelRequested,
    MissionCreated,
    MissionSelected,
    MissionStartRequested,
    SessionEventReceived,
)


class TestSessionEventReceived:
    def test_stores_event(self):
        class FakeEvent:
            event_type = "agent.thinking.started"

        msg = SessionEventReceived(event=FakeEvent())
        assert msg.event.event_type == "agent.thinking.started"


class TestMissionStartRequested:
    def test_stores_brief(self):
        msg = MissionStartRequested(brief="Analyse the market")
        assert msg.brief == "Analyse the market"


class TestMissionCancelRequested:
    def test_can_instantiate(self):
        msg = MissionCancelRequested()
        assert isinstance(msg, MissionCancelRequested)


class TestMissionSelected:
    def test_stores_id_and_name(self):
        msg = MissionSelected(mission_id="p-1", mission_name="Alpha")
        assert msg.mission_id == "p-1"
        assert msg.mission_name == "Alpha"


class TestMissionCreated:
    def test_stores_name_and_description(self):
        msg = MissionCreated(mission_name="Beta", description="A new mission")
        assert msg.mission_name == "Beta"
        assert msg.description == "A new mission"

    def test_description_defaults_to_empty(self):
        msg = MissionCreated(mission_name="Gamma")
        assert msg.description == ""


class TestAgentSelected:
    def test_stores_agent_name(self):
        msg = AgentSelected(agent_name="modules.agents.researcher")
        assert msg.agent_name == "modules.agents.researcher"
