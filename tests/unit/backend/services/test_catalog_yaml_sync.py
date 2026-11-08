"""Unit tests for the catalog YAML sync rules: what counts as drift and how a file is edited.

No database: a catalog row is a plain namespace, a YAML file is a string.
"""

import re
from types import SimpleNamespace

import pytest

from modules.backend.core.config import get_app_config, get_mission_control_config
from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema
from modules.backend.services.catalog_yaml_sync import (
    _dump,
    _same,
    _yaml,
    apply_changes,
    diff_agent,
)

SAMPLE = """\
# Header comment
agent_name: test.sync.agent
agent_type: vertical
description: "A test agent"
enabled: true
model: "foundry:gpt-5-mini"  # pinned for cost
max_input_length: 1000
max_budget_usd: 0.10

execution:
  mode: local

keywords:
  - alpha  # first
  - beta
tools:
  - system.get_app_info
scope:
  read:
    - docs/
  write: []
"""

# Defaults come from the schemas and config the sync reads, so no value is repeated here.
DEFAULT_TIMEOUT = get_app_config().application.timeouts.agent_task
DEFAULT_RETRIES = get_mission_control_config().dispatch.default_retry_budget
SLOW_TIMEOUT = DEFAULT_TIMEOUT * 5
DEFAULT_TEMPERATURE = AgentModelSchema.model_fields["temperature"].default
DEFAULT_MAX_TOKENS = AgentModelSchema.model_fields["max_tokens"].default
DEFAULT_VERSION = AgentConfigSchema.model_fields["version"].default
DEFAULT_ENGINE = AgentConfigSchema.model_fields["engine"].default
DEFAULT_VISIBILITY = AgentConfigSchema.model_fields["visibility"].default


def _model(name: str, **overrides) -> dict:
    """A catalog model_config_json with the schema defaults, plus ``overrides``."""
    return {
        "name": name,
        "temperature": DEFAULT_TEMPERATURE,
        "max_tokens": DEFAULT_MAX_TOKENS,
        **overrides,
    }


def _row(**overrides) -> SimpleNamespace:
    """A catalog row that matches SAMPLE exactly."""
    row = dict(
        description="A test agent",
        enabled=True,
        chat_enabled=False,
        version=DEFAULT_VERSION,
        visibility=DEFAULT_VISIBILITY,
        keywords=["alpha", "beta"],
        tools=["system.get_app_info"],
        model_config_json=_model("foundry:gpt-5-mini"),
        scope={"read": ["docs/"], "write": []},
        interface=None,
        engine=DEFAULT_ENGINE,
        effort=None,
        thinking_budget_json=None,
        max_budget_usd=0.1,
        max_input_length=1000,
        constraints={
            "timeout_seconds": DEFAULT_TIMEOUT,
            "cost_ceiling_usd": 0.1,
            "retry_budget": 2,
        },
    )
    row.update(overrides)
    return SimpleNamespace(**row)


def _sync(row: SimpleNamespace, text: str = SAMPLE) -> tuple[list, str]:
    """Diff ``text`` against ``row`` and return the changes and the edited text."""
    doc = _yaml().load(text)
    changes = diff_agent(row, doc)
    apply_changes(doc, changes)
    return changes, _dump(doc)


class TestNoDrift:
    def test_a_row_that_matches_reports_nothing(self):
        assert diff_agent(_row(), _yaml().load(SAMPLE)) == []

    def test_database_defaults_do_not_force_keys_into_the_file(self):
        changes, text = _sync(_row())

        assert changes == []
        assert text == SAMPLE

    def test_the_sample_round_trips_byte_for_byte(self):
        assert _dump(_yaml().load(SAMPLE)) == SAMPLE

    def test_equal_numbers_in_different_notation_are_the_same(self):
        assert _same(0.1, 0.10)
        assert _same(1, 1.0)
        assert not _same(True, 1)
        assert not _same(0.1, 0.2)


class TestModel:
    def test_a_new_model_name_keeps_the_quotes_and_the_inline_comment(self):
        row = _row(model_config_json=_model("foundry:claude-opus-5-5"))

        changes, text = _sync(row)

        assert [(c.field, c.database_value) for c in changes] == [
            ("model.name", "foundry:claude-opus-5-5")
        ]
        assert re.search(r'model: "foundry:claude-opus-5-5"\s+# pinned for cost', text)
        assert "gpt-5-mini" not in text

    def test_a_plain_scalar_model_stays_plain(self):
        plain = SAMPLE.replace('model: "foundry:gpt-5-mini"', "model: foundry:gpt-5-mini")

        _, text = _sync(_row(model_config_json=_model("foundry:gpt-5.4")), plain)

        assert re.search(r"model: foundry:gpt-5.4\s+# pinned for cost", text)

    def test_a_different_temperature_turns_the_flat_model_into_a_block(self):
        row = _row(
            model_config_json=_model("foundry:gpt-5-mini", temperature=DEFAULT_TEMPERATURE + 0.5)
        )

        changes, text = _sync(row)

        assert [c.field for c in changes] == ["model.temperature"]
        assert re.search(r"model:\s+# pinned for cost\n  name:", text)
        assert f"temperature: {DEFAULT_TEMPERATURE + 0.5}" in text
        assert "max_tokens" not in text

    def test_a_block_model_keeps_the_keys_the_catalog_does_not_store(self):
        block = SAMPLE.replace(
            'model: "foundry:gpt-5-mini"  # pinned for cost',
            'model:\n  name: "foundry:gpt-5-mini"\n  output_mode: native\n  betas: [one]',
        )
        row = _row(model_config_json=_model("foundry:gpt-5.4"))

        _, text = _sync(row, block)

        assert 'name: "foundry:gpt-5.4"' in text
        assert "output_mode: native" in text
        assert "betas: [one]" in text


class TestOtherFields:
    def test_a_changed_list_is_replaced_and_other_comments_survive(self):
        changes, text = _sync(_row(tools=["system.get_app_info", "system.check_services"]))

        assert [c.field for c in changes] == ["tools"]
        assert "  - system.check_services" in text
        assert "  - alpha  # first" in text
        assert "# Header comment" in text

    def test_a_list_shortened_in_the_catalog_is_shortened_in_the_file(self):
        _, text = _sync(_row(keywords=["alpha"]))

        assert "  - alpha  # first" in text
        assert "beta" not in text

    def test_a_timeout_the_file_lacks_is_inserted(self):
        changes, text = _sync(_row(constraints={"timeout_seconds": SLOW_TIMEOUT}))

        assert [(c.field, c.yaml_value, c.database_value) for c in changes] == [
            ("timeout_seconds", DEFAULT_TIMEOUT, SLOW_TIMEOUT)
        ]
        assert f"timeout_seconds: {SLOW_TIMEOUT}" in text

    def test_a_timeout_equal_to_the_default_is_not_inserted(self):
        changes, _ = _sync(_row(constraints={"timeout_seconds": DEFAULT_TIMEOUT}))

        assert changes == []

    def test_a_value_the_catalog_has_cleared_is_removed_from_the_file(self):
        with_effort = SAMPLE.replace("enabled: true\n", "enabled: true\neffort: high\n")

        changes, text = _sync(_row(), with_effort)

        assert [(c.field, c.yaml_value, c.database_value) for c in changes] == [
            ("effort", "high", None)
        ]
        assert "effort" not in text

    def test_a_nested_value_is_created_when_its_parent_is_missing(self):
        no_scope = SAMPLE.replace("scope:\n  read:\n    - docs/\n  write: []\n", "")

        changes, text = _sync(_row(scope={"read": ["docs/"], "write": []}), no_scope)

        assert [c.field for c in changes] == ["scope.read"]
        assert "scope:\n  read:\n    - docs/" in text

    def test_a_boolean_and_a_description_change_together(self):
        changes, text = _sync(_row(enabled=False, description="Renamed"))

        assert sorted(c.field for c in changes) == ["description", "enabled"]
        assert "enabled: false" in text
        assert 'description: "Renamed"' in text

    @pytest.mark.parametrize("budget", [0.10, 0.1, 0.1000000001])
    def test_a_budget_in_a_different_notation_is_not_drift(self, budget):
        assert diff_agent(_row(max_budget_usd=budget), _yaml().load(SAMPLE)) == []

    def test_applying_the_changes_leaves_nothing_to_sync(self):
        row = _row(
            enabled=False,
            tools=["system.check_services"],
            constraints={"timeout_seconds": SLOW_TIMEOUT},
            model_config_json=_model(
                "foundry:gpt-5.4",
                temperature=DEFAULT_TEMPERATURE + 0.2,
                max_tokens=DEFAULT_MAX_TOKENS // 2,
            ),
        )

        _, text = _sync(row)

        assert diff_agent(row, _yaml().load(text)) == []


class TestIgnoredAndEmptyValues:
    def test_an_empty_thinking_budget_is_the_same_as_none(self):
        assert diff_agent(_row(thinking_budget_json={}), _yaml().load(SAMPLE)) == []

    def test_a_real_thinking_budget_is_still_drift(self):
        changes = diff_agent(
            _row(thinking_budget_json={"max_thinking_tokens": 2000}), _yaml().load(SAMPLE)
        )

        assert [c.field for c in changes] == ["thinking_budget"]

    def test_effort_is_synced_for_an_in_process_agent_too(self):
        changes = diff_agent(_row(effort="medium"), _yaml().load(SAMPLE))

        assert [(c.field, c.database_value) for c in changes] == [("effort", "medium")]

    def test_effort_on_a_cli_engine_is_synced(self):
        changes = diff_agent(_row(engine="claude_code", effort="medium"), _yaml().load(SAMPLE))

        assert sorted(c.field for c in changes) == ["effort", "engine"]


class TestConstraintsAsTheRosterAppliesThem:
    def test_a_missing_retry_budget_is_the_config_default_not_drift(self):
        assert diff_agent(_row(constraints={}), _yaml().load(SAMPLE)) == []

    def test_a_different_retry_budget_is_inserted_into_the_file(self):
        changes, text = _sync(_row(constraints={"retry_budget": DEFAULT_RETRIES + 3}))

        assert [(c.field, c.yaml_value, c.database_value) for c in changes] == [
            ("retry_budget", DEFAULT_RETRIES, DEFAULT_RETRIES + 3)
        ]
        assert f"retry_budget: {DEFAULT_RETRIES + 3}" in text

    def test_zero_retries_is_a_real_value_not_a_missing_one(self):
        changes, text = _sync(_row(constraints={"retry_budget": 0}))

        assert [(c.field, c.database_value) for c in changes] == [("retry_budget", 0)]
        assert "retry_budget: 0" in text

    def test_a_retry_budget_equal_to_the_default_is_not_inserted(self):
        assert (
            diff_agent(_row(constraints={"retry_budget": DEFAULT_RETRIES}), _yaml().load(SAMPLE))
            == []
        )

    def test_a_missing_timeout_is_the_config_default_not_drift(self):
        assert diff_agent(_row(constraints={}), _yaml().load(SAMPLE)) == []


class TestVisibility:
    def test_the_default_visibility_is_not_forced_into_the_file(self):
        assert diff_agent(_row(visibility=DEFAULT_VISIBILITY), _yaml().load(SAMPLE)) == []

    def test_a_restricted_agent_gets_its_visibility_written(self):
        changes, text = _sync(_row(visibility="system"))

        assert [(c.field, c.yaml_value, c.database_value) for c in changes] == [
            ("visibility", DEFAULT_VISIBILITY, "system")
        ]
        assert "visibility: system" in text
