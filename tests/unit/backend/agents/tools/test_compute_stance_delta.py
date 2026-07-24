"""Tests for compute_stance_delta tool (Plan 79 §9 + S5 + C2).

Deterministic stop-signal computation: aggregate embedding distance
between rounds + confidence delta + active-revision check. No LLM, no
mission state.
"""

from __future__ import annotations

import pytest

from modules.backend.tools.compute_stance_delta import (
    TOOL_DEF,
    _cosine_distance,
    _has_active_revision,
    compute_stance_delta,
)


# Reusable mock embedder (FakeEmbedder from core.embeddings is the real
# fallback in tests anyway; we use an explicit fake to make the per-debater
# distance assertions deterministic).
class _MockEmbedder:
    """Returns deterministic vectors per input string."""

    def __init__(self, mapping: dict[str, list[float]] | None = None):
        self.mapping = mapping or {}

    async def embed(self, text: str) -> list[float]:
        return self.mapping.get(text, [0.0, 0.0, 0.0])


def _turn(position: str, confidence: float = 0.5, decision: str = "HOLD") -> dict:
    return {
        "position": position,
        "confidence": confidence,
        "decision": decision,
    }


class TestComputeStanceDelta:
    @pytest.mark.asyncio
    async def test_stable_round_returns_should_continue_false(self, monkeypatch):
        # Identical positions, no active revision → should stop.
        embedder = _MockEmbedder(
            {
                "p1": [1.0, 0.0, 0.0],
            }
        )
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        prev = {
            "systems": _turn("p1"),
            "quant": _turn("p1"),
            "empiricist": _turn("p1"),
            "ethicist": _turn("p1"),
        }
        curr = {
            "systems": _turn("p1"),
            "quant": _turn("p1"),
            "empiricist": _turn("p1"),
            "ethicist": _turn("p1"),
        }
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is False
        assert result["delta"] < 0.15

    @pytest.mark.asyncio
    async def test_active_revision_forces_continue(self, monkeypatch):
        # Even with zero embedding/confidence delta, a CONCEDE_PARTIAL
        # decision forces should_continue=True. The decision is the
        # signal that the deliberation moved meaningfully.
        embedder = _MockEmbedder({"p1": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        prev = {
            "systems": _turn("p1"),
            "quant": _turn("p1"),
            "empiricist": _turn("p1"),
            "ethicist": _turn("p1"),
        }
        curr = {
            "systems": _turn("p1", decision="CONCEDE_PARTIAL"),
            "quant": _turn("p1"),
            "empiricist": _turn("p1"),
            "ethicist": _turn("p1"),
        }
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is True
        # The reasoning string captures the active revision flag.
        assert "active_revision=True" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_large_text_change_forces_continue(self, monkeypatch):
        # Orthogonal embeddings → cosine distance ~ 1.0.
        embedder = _MockEmbedder(
            {
                "p1": [1.0, 0.0, 0.0],
                "p2": [0.0, 1.0, 0.0],
            }
        )
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        prev = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        curr = {d: _turn("p2") for d in ("systems", "quant", "empiricist", "ethicist")}
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is True
        assert result["delta"] > 0.15

    @pytest.mark.asyncio
    async def test_confidence_delta_forces_continue(self, monkeypatch):
        # Identical position text, but a big confidence swing → max()
        # picks up the confidence delta as the per-debater value.
        embedder = _MockEmbedder({"p1": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        prev = {
            d: _turn("p1", confidence=0.9) for d in ("systems", "quant", "empiricist", "ethicist")
        }
        curr = {
            d: _turn("p1", confidence=0.3) for d in ("systems", "quant", "empiricist", "ethicist")
        }
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        # confidence_delta = 0.6 > threshold → continue
        assert result["should_continue"] is True

    @pytest.mark.asyncio
    async def test_missing_previous_returns_max_distance(self, monkeypatch):
        embedder = _MockEmbedder({"p1": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        # previous_round empty → every debater gets 1.0 delta → continue.
        curr = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        result = await compute_stance_delta(
            previous_round={},
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is True
        for d in ("systems", "quant", "empiricist", "ethicist"):
            assert result["per_debater"][d] == 1.0

    @pytest.mark.asyncio
    async def test_embedding_provider_failure_forces_continue(self, monkeypatch):
        # When FailOpenEmbedder returns [] (provider unavailable), we
        # treat as max distance and force continue.
        class _FailingEmbedder:
            async def embed(self, text):
                return []

        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: _FailingEmbedder(),
        )
        prev = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        curr = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is True

    def test_tool_def_has_empty_deps(self):
        # Plan 79 C2 — no mission_id injection. The tool is pure.
        assert TOOL_DEF["deps"] == []

    def test_tool_def_metadata(self):
        assert TOOL_DEF["name"] == "compute_stance_delta"
        assert TOOL_DEF["category"] == "workflow"

    def test_cosine_distance_orthogonal_is_one(self):
        assert _cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)

    def test_cosine_distance_identical_is_zero(self):
        assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

    def test_cosine_distance_zero_vector_is_max(self):
        # Edge case: zero vector → distance 1.0 (cannot normalise).
        assert _cosine_distance([0.0, 0.0], [1.0, 0.0]) == 1.0

    @pytest.mark.asyncio
    async def test_emits_gate_field_matching_should_continue(self, monkeypatch):
        # The decision rule resolver needs the option-key string, not a
        # bool. compute_stance_delta emits both for downstream flexibility.
        embedder = _MockEmbedder({"p1": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(
            "modules.backend.tools.compute_stance_delta.get_embedder",
            lambda: embedder,
        )
        # Stable case → gate=halt
        prev = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        curr = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        result = await compute_stance_delta(
            previous_round=prev,
            current_round=curr,
            threshold=0.15,
        )
        assert result["should_continue"] is False
        assert result["gate"] == "halt"

        # Active revision → gate=continue
        curr2 = {d: _turn("p1") for d in ("systems", "quant", "empiricist", "ethicist")}
        curr2["systems"] = _turn("p1", decision="CONCEDE_PARTIAL")
        result2 = await compute_stance_delta(
            previous_round=prev,
            current_round=curr2,
            threshold=0.15,
        )
        assert result2["should_continue"] is True
        assert result2["gate"] == "continue"

    def test_has_active_revision_detects_decisions(self):
        assert _has_active_revision({"decision": "CONCEDE_PARTIAL"}) is True
        assert _has_active_revision({"decision": "CONCEDE_FULL"}) is True
        assert _has_active_revision({"decision": "REFINE"}) is True
        assert _has_active_revision({"decision": "HOLD"}) is False
        assert _has_active_revision({}) is False
