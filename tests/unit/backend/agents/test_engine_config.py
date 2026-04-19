"""
Unit tests for engine/effort fields in AgentConfigSchema (Plan 55 Phase A).

Validates the engine field validator, effort field validator,
and the CLI engine interface constraint.
"""

import pytest
from pydantic import ValidationError

from modules.backend.agents.config_schema import AgentConfigSchema


def _make_config(**overrides) -> dict:
    """Build a minimal valid agent config dict, with overrides."""
    base = {
        "agent_name": "test.dummy.agent",
        "agent_type": "vertical",
        "description": "A test agent",
        "enabled": True,
        "model": "anthropic:claude-haiku-4-5-20251001",
        "max_input_length": 5000,
        "max_budget_usd": 1.0,
        "execution": {"mode": "local"},
    }
    base.update(overrides)
    return base


# =============================================================================
# Engine field validation
# =============================================================================


class TestEngineValidation:
    """Tests for the engine field on AgentConfigSchema."""

    def test_default_engine_is_pydantic_ai(self):
        config = AgentConfigSchema(**_make_config())
        assert config.engine == "pydantic_ai"

    def test_engine_claude_code_accepted(self):
        config = AgentConfigSchema(**_make_config(engine="claude_code"))
        assert config.engine == "claude_code"

    def test_engine_codex_accepted(self):
        config = AgentConfigSchema(**_make_config(engine="codex"))
        assert config.engine == "codex"

    def test_engine_copilot_accepted(self):
        config = AgentConfigSchema(**_make_config(engine="copilot"))
        assert config.engine == "copilot"

    def test_engine_invalid_raises(self):
        with pytest.raises(ValidationError, match="engine must be one of"):
            AgentConfigSchema(**_make_config(engine="invalid_engine"))

    def test_engine_pydantic_ai_explicit(self):
        config = AgentConfigSchema(**_make_config(engine="pydantic_ai"))
        assert config.engine == "pydantic_ai"


# =============================================================================
# Effort field validation
# =============================================================================


class TestEffortValidation:
    """Tests for the effort field on AgentConfigSchema."""

    def test_effort_default_is_none(self):
        config = AgentConfigSchema(**_make_config())
        assert config.effort is None

    def test_effort_high_accepted(self):
        config = AgentConfigSchema(**_make_config(effort="high"))
        assert config.effort == "high"

    def test_effort_medium_accepted(self):
        config = AgentConfigSchema(**_make_config(effort="medium"))
        assert config.effort == "medium"

    def test_effort_low_accepted(self):
        config = AgentConfigSchema(**_make_config(effort="low"))
        assert config.effort == "low"

    def test_effort_invalid_raises(self):
        with pytest.raises(ValidationError, match="effort must be low/medium/high"):
            AgentConfigSchema(**_make_config(effort="invalid"))

    def test_effort_none_explicit(self):
        config = AgentConfigSchema(**_make_config(effort=None))
        assert config.effort is None


# =============================================================================
# CLI engine interface constraint
# =============================================================================


class TestCliEngineInterfaceValidator:
    """Tests for _validate_cli_engine_interface model validator."""

    def test_cli_engine_with_output_fields_raises(self):
        """CLI engines cannot declare interface.output fields."""
        with pytest.raises(ValidationError, match="CLI engines return unstructured output"):
            AgentConfigSchema(
                **_make_config(
                    engine="claude_code",
                    interface={
                        "input": {"query": "str"},
                        "output": {"summary": "str"},
                    },
                )
            )

    def test_cli_engine_with_input_only_interface_ok(self):
        """CLI engines can have interface.input fields (no output)."""
        config = AgentConfigSchema(
            **_make_config(
                engine="claude_code",
                interface={
                    "input": {"query": "str"},
                    "output": {},
                },
            )
        )
        assert config.interface is not None
        assert config.interface.input == {"query": "str"}

    def test_cli_engine_with_no_interface_ok(self):
        """CLI engines with interface=None are fine."""
        config = AgentConfigSchema(
            **_make_config(engine="claude_code", interface=None)
        )
        assert config.interface is None

    def test_pydantic_ai_with_output_fields_ok(self):
        """PydanticAI engine can have interface.output fields."""
        config = AgentConfigSchema(
            **_make_config(
                engine="pydantic_ai",
                interface={
                    "input": {"query": "str"},
                    "output": {"summary": "str"},
                },
            )
        )
        assert config.interface.output == {"summary": "str"}

    def test_codex_engine_with_output_fields_raises(self):
        """Codex engine also cannot have output fields."""
        with pytest.raises(ValidationError, match="CLI engines return unstructured output"):
            AgentConfigSchema(
                **_make_config(
                    engine="codex",
                    interface={
                        "input": {},
                        "output": {"result": "str"},
                    },
                )
            )

    def test_copilot_engine_with_output_fields_raises(self):
        """Copilot engine also cannot have output fields."""
        with pytest.raises(ValidationError, match="CLI engines return unstructured output"):
            AgentConfigSchema(
                **_make_config(
                    engine="copilot",
                    interface={
                        "input": {},
                        "output": {"result": "str"},
                    },
                )
            )
