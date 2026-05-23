"""Tests for halt_workflow tool (Plan 79 §9.2 / S1)."""

from __future__ import annotations

import pytest

from modules.backend.tools.halt_workflow import TOOL_DEF, halt_workflow


class TestHaltWorkflow:
    @pytest.mark.asyncio
    async def test_always_raises_runtime_error(self):
        # The tool's job is to raise — the wave engine catches
        # RuntimeError specifically and marks the run failed.
        with pytest.raises(RuntimeError) as exc_info:
            await halt_workflow(reason="Test halt")
        assert "Workflow halted" in str(exc_info.value)
        assert "Test halt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_channel_arg_accepted(self):
        # The channel arg is informational; it does not change behaviour.
        with pytest.raises(RuntimeError):
            await halt_workflow(reason="x", channel="telegram")

    @pytest.mark.asyncio
    async def test_reason_appears_in_exception(self):
        with pytest.raises(RuntimeError) as exc_info:
            await halt_workflow(
                reason="Research packet failed verification: bad sources",
            )
        assert "Research packet failed verification" in str(exc_info.value)
        assert "bad sources" in str(exc_info.value)

    def test_tool_def_has_empty_deps(self):
        # No mission_id injection — the tool is generic.
        assert TOOL_DEF["deps"] == []

    def test_tool_def_metadata(self):
        assert TOOL_DEF["name"] == "halt_workflow"
        assert TOOL_DEF["category"] == "workflow"
