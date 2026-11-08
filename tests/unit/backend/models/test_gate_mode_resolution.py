"""Tests for resolve_gate_mode (Plan 88 steps 88.0.4 and 88.0.5): fail closed to MANUAL."""

import pytest

from modules.backend.models.mission_plan import (
    FAIL_CLOSED_GATE_MODE,
    VALID_GATE_MODES,
    resolve_gate_mode,
)


def test_none_resolves_manual():
    assert resolve_gate_mode(None) == "manual"


def test_unknown_resolves_manual():
    assert resolve_gate_mode("bogus") == FAIL_CLOSED_GATE_MODE


def test_workflow_managed_resolves_manual():
    assert resolve_gate_mode("workflow_managed") == "manual"


@pytest.mark.parametrize("mode", sorted(VALID_GATE_MODES))
def test_valid_modes_pass_through(mode):
    assert resolve_gate_mode(mode) == mode
