"""Tests for agent roster loading and validation."""

import pytest

from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterInterfaceSchema,
    RosterModelSchema,
)


def _make_entry(name: str = "test.agent", version: str = "1.0.0") -> RosterAgentEntry:
    """Create a minimal roster entry for testing."""
    return RosterAgentEntry(
        agent_name=name,
        agent_version=version,
        description="Test agent",
        model=RosterModelSchema(name="test-model"),
        interface=RosterInterfaceSchema(
            input={"query": "string"},
            output={"result": "string", "confidence": "float"},
        ),
    )


class TestRoster:
    def test_get_agent_by_name_and_version(self):
        roster = Roster(agents=[_make_entry()])
        assert roster.get_agent("test.agent", "1.0.0") is not None
        assert roster.get_agent("test.agent", "2.0.0") is None
        assert roster.get_agent("nonexistent", "1.0.0") is None

    def test_get_agent_by_name_only(self):
        roster = Roster(agents=[_make_entry()])
        assert roster.get_agent_by_name("test.agent") is not None
        assert roster.get_agent_by_name("nonexistent") is None

    def test_agent_names(self):
        roster = Roster(agents=[_make_entry("a"), _make_entry("b")])
        assert roster.agent_names == ["a", "b"]

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            RosterAgentEntry(
                agent_name="test",
                agent_version="1.0.0",
                description="Test",
                model=RosterModelSchema(name="test"),
                interface=RosterInterfaceSchema(),
                unknown_field="bad",
            )


