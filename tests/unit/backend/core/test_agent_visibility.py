"""Visibility is declared on the agent, with one default and one set of allowed values."""

import pytest
from pydantic import ValidationError

from modules.backend.api.v1.endpoints.admin import (
    CatalogCreateRequest,
    CatalogUpdateRequest,
)
from modules.backend.schemas.agent_config import AgentConfigSchema

DEFAULT = AgentConfigSchema.model_fields["visibility"].default

MINIMAL_AGENT = {
    "agent_name": "test.visibility.agent",
    "agent_type": "vertical",
    "description": "A test agent",
    "enabled": True,
    "model": "foundry:gpt-fixture",
    "max_input_length": 1000,
    "max_budget_usd": 0.1,
    "execution": {"mode": "local"},
}

CREATE = {"agent_name": "x.y.agent", "agent_type": "vertical", "description": "d"}


class TestAgentConfig:
    def test_an_agent_that_declares_nothing_gets_the_default(self):
        assert AgentConfigSchema(**MINIMAL_AGENT).visibility == DEFAULT

    def test_an_agent_can_declare_itself_restricted(self):
        assert AgentConfigSchema(**MINIMAL_AGENT, visibility="system").visibility == "system"

    def test_an_unknown_visibility_is_rejected(self):
        with pytest.raises(ValidationError):
            AgentConfigSchema(**MINIMAL_AGENT, visibility="secret")

    def test_the_type_of_an_agent_does_not_decide_its_visibility(self):
        config = AgentConfigSchema(**{**MINIMAL_AGENT, "agent_type": "system"})

        assert config.visibility == DEFAULT


class TestAdminRequests:
    def test_a_create_request_without_visibility_leaves_it_to_the_default(self):
        assert CatalogCreateRequest(**CREATE).visibility is None

    def test_a_create_request_accepts_the_allowed_values(self):
        assert CatalogCreateRequest(**CREATE, visibility="system").visibility == "system"

    def test_a_create_request_rejects_anything_else(self):
        with pytest.raises(ValidationError):
            CatalogCreateRequest(**CREATE, visibility="secret")

    def test_an_update_request_rejects_anything_else(self):
        with pytest.raises(ValidationError):
            CatalogUpdateRequest(visibility="secret")
