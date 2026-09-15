"""Unit tests for the Director's mission introspection tool implementations.

These were closures inside `register_mission_tools`, reachable only
through a PydanticAI agent, and so had no coverage. No LLM and no agent
runtime is involved (P11).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.backend.agents.mission.director.tool_helpers import CompactResult, ToolRefusal
from modules.backend.agents.mission.director.tools.browse_catalog import (
    _as_catalog_entry,
    _matches_keyword,
    _searchable_text,
)
from modules.backend.agents.mission.director.tools.check_background_tasks import _as_task
from modules.backend.agents.mission.director.tools.get_execution_detail import _as_detail
from modules.backend.agents.mission.director.tools.list_tools import list_tools


class _CatalogEntry:
    """Stand-in for an AgentCatalog row, with only the read fields."""

    def __init__(
        self,
        agent_name="research.analyst.agent",
        description="Analyses research findings",
        keywords=None,
        agent_type="vertical",
        enabled=True,
        tools=None,
        scope=None,
        interface="chat",
        constraints=None,
        chat_enabled=True,
    ):
        self.agent_name = agent_name
        self.description = description
        self.keywords = keywords
        self.agent_type = agent_type
        self.enabled = enabled
        self.tools = tools
        self.scope = scope
        self.interface = interface
        self.constraints = constraints
        self.chat_enabled = chat_enabled


class TestListTools:
    def test_reports_count_and_list(self):
        tools = [{"name": "get_plan", "description": "Read the plan"}]
        result = list_tools(tools)
        assert result["available_tools"] == 1
        assert result["tools"] == tools

    def test_constrains_the_model_to_the_list(self):
        """The note is the only thing stopping invented tool names."""
        assert "ONLY" in list_tools([])["note"]

    def test_handles_an_empty_surface(self):
        assert list_tools([]) == {
            "available_tools": 0,
            "tools": [],
            "note": "You can ONLY call tools in this list. Do not invent tool names.",
        }


class TestBrowseCatalogFiltering:
    def test_no_keyword_matches_everything(self):
        assert _matches_keyword(_CatalogEntry(), None) is True
        assert _matches_keyword(_CatalogEntry(), "") is True

    def test_matches_on_description_case_insensitively(self):
        entry = _CatalogEntry(description="Runs a Security Scan")
        assert _matches_keyword(entry, "security") is True
        assert _matches_keyword(entry, "SECURITY") is True

    def test_matches_on_keywords_and_agent_name(self):
        assert _matches_keyword(_CatalogEntry(keywords=["pentest"]), "pentest") is True
        assert _matches_keyword(_CatalogEntry(agent_name="code.qa.agent"), "qa") is True

    def test_excludes_a_non_match(self):
        assert _matches_keyword(_CatalogEntry(description="Writes docs"), "kubernetes") is False

    def test_tolerates_null_description_and_keywords(self):
        entry = _CatalogEntry(description=None, keywords=None)
        assert _matches_keyword(entry, "anything") is False
        assert _matches_keyword(entry, None) is True

    def test_searchable_text_concatenates_without_a_separator(self):
        """Pre-existing behaviour, asserted so a future change is deliberate:
        description and the joined keywords run together, so a keyword
        spanning that join can match."""
        entry = _CatalogEntry(description="alpha", keywords=["beta"], agent_name="gamma")
        assert _searchable_text(entry) == "alphabetagamma"


class TestAsCatalogEntry:
    def test_flags_team_membership(self):
        entry = _CatalogEntry(agent_name="research.analyst.agent")
        assert _as_catalog_entry(entry, {"research.analyst.agent"})["on_team"] is True
        assert _as_catalog_entry(entry, set())["on_team"] is False

    def test_coerces_nulls_to_empty_collections(self):
        shaped = _as_catalog_entry(_CatalogEntry(keywords=None, tools=None, scope=None), set())
        assert shaped["keywords"] == []
        assert shaped["tools"] == []
        assert shaped["scope"] == {}

    def test_preserves_disabled_state(self):
        """Disabled agents are listed, so the model can explain why one is
        unavailable rather than claim it does not exist."""
        assert _as_catalog_entry(_CatalogEntry(enabled=False), set())["enabled"] is False


class _Status:
    def __init__(self, value):
        self.value = value


class _Record:
    def __init__(self, status, started_at=None, completed_at=None, created_at=None):
        self.id = "rec-1"
        self.objective_statement = "Scan the API"
        self.status = status
        self.roster_name = "security"
        self.total_cost_usd = 1.25
        self.cost_ceiling_usd = 10.0
        self.started_at = started_at
        self.completed_at = completed_at
        self.created_at = created_at
        self.execution_outcome_json = {"ok": True}
        self.workflow_run_id = "wr-1"
        self.workflow_step_id = "ws-1"
        self.task_type = "plan_dispatch"
        self.temporal_workflow_id = "tw-1"


class TestAsDetail:
    def test_unwraps_an_enum_status(self):
        assert _as_detail(_Record(_Status("COMPLETED")))["status"] == "COMPLETED"

    def test_accepts_a_plain_string_status(self):
        assert _as_detail(_Record("RUNNING"))["status"] == "RUNNING"

    def test_renders_absent_timestamps_as_none(self):
        shaped = _as_detail(_Record("RUNNING"))
        assert shaped["started_at"] is None
        assert shaped["completed_at"] is None

    def test_stringifies_present_timestamps(self):
        when = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        assert "2026-09-15" in _as_detail(_Record("DONE", started_at=when))["started_at"]


class TestAsTask:
    def test_accepts_a_plain_string_status(self):
        assert _as_task(_Record("RUNNING"))["status"] == "RUNNING"

    def test_unwraps_an_enum_status(self):
        assert _as_task(_Record(_Status("PENDING")))["status"] == "PENDING"

    def test_uses_isoformat_for_timestamps(self):
        """_as_task uses isoformat where _as_detail uses str(); both are
        pre-existing and asserted so the difference stays deliberate."""
        when = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        assert _as_task(_Record("DONE", created_at=when))["created_at"] == when.isoformat()

    def test_renders_absent_timestamps_as_none(self):
        shaped = _as_task(_Record("RUNNING"))
        assert shaped["created_at"] is None
        assert shaped["started_at"] is None
        assert shaped["completed_at"] is None


class TestCompactResult:
    def test_carries_its_payload_unchanged(self):
        """Used for the 'nothing found' cases, which were serialised
        without indentation before the implementations were extracted."""
        payload = {"tasks": [], "message": "No background tasks found."}
        assert CompactResult(payload).payload == payload

    def test_is_not_an_error(self):
        assert not isinstance(CompactResult({}), ToolRefusal)

    def test_is_frozen(self):
        result = CompactResult({"a": 1})
        with pytest.raises(Exception):
            result.payload = {"b": 2}
