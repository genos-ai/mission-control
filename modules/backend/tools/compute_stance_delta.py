"""
Tool: compute_stance_delta

Deterministic early-stop computation for the Think Tank workflow
(Plan 79 §9). Computes a per-debater stance delta between two
consecutive rounds and aggregates into a single should_continue flag.

If the aggregate delta is below the threshold AND no debater issued
CONCEDE_PARTIAL, CONCEDE_FULL, or REFINE in the most recent round,
returns should_continue=False (the deliberation has stabilised). Else
returns should_continue=True.

Critical: this is a STOPPING signal, not a quality measure. Two
debaters can converge via shared hidden assumptions and the stance
vector will not see it — that is the critic's ConvergenceFlag job.

Pure computation, no mission state. deps=[] so the wave engine does
not inject mission_id.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from modules.backend.core.embeddings import get_embedder
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def compute_stance_delta(
    *,
    previous_round: dict[str, dict[str, Any]],
    current_round: dict[str, dict[str, Any]],
    threshold: float = 0.15,
) -> dict[str, Any]:
    """Compute per-debater stance delta and aggregate stop signal.

    Args:
        previous_round: {debater_id: DebaterTurn dict} from round N-1.
        current_round: {debater_id: DebaterTurn dict} from round N.
        threshold: delta below which we consider stance stable.

    Returns:
        StanceDelta dict with delta, threshold, should_continue,
        per_debater, reasoning.
    """
    embedder = get_embedder()

    # Parallel embedding computation per debater (Plan 79 S5 fix —
    # avoids 8 sequential awaits adding 2-4 s of serial latency per
    # early-stop check).
    debater_ids = list(current_round.keys())
    pair_results = await asyncio.gather(*[
        _per_debater_delta(debater_id, previous_round.get(debater_id),
                           current_round[debater_id], embedder)
        for debater_id in debater_ids
    ])

    per_debater = dict(pair_results)
    any_active_revision = any(
        _has_active_revision(current_round[d]) for d in debater_ids
    )

    # Aggregate delta — mean across debaters. The threshold is applied
    # to this aggregate, not to any single debater.
    aggregate = (
        sum(per_debater.values()) / max(len(per_debater), 1)
    )

    stance_stable = aggregate < threshold
    should_continue = (not stance_stable) or any_active_revision

    reasoning = (
        f"aggregate delta {aggregate:.3f} "
        f"{'<' if stance_stable else '>='} threshold {threshold:.3f}; "
        f"active_revision={any_active_revision}"
    )

    logger.info(
        "Stance delta computed",
        extra={
            "delta": aggregate,
            "threshold": threshold,
            "should_continue": should_continue,
            "per_debater": per_debater,
            "any_active_revision": any_active_revision,
        },
    )

    return {
        "delta": aggregate,
        "threshold": threshold,
        "should_continue": should_continue,
        # String form matching the stop-rN decision option keys
        # ("continue" / "halt"). The decision rule resolver expects
        # the expression result to equal an option key, not a bool.
        "gate": "continue" if should_continue else "halt",
        "per_debater": per_debater,
        "reasoning": reasoning,
    }


async def _per_debater_delta(
    debater_id: str,
    prev: dict[str, Any] | None,
    curr: dict[str, Any],
    embedder,
) -> tuple[str, float]:
    """Embed prev/curr positions and return cosine distance.

    Falls back to 1.0 (max change) when prev is None — this is the
    round-1 case where each debater is being compared against their
    blind opening; "no prior" means "treat as fully changed".

    The confidence-delta is mixed in via max() so large confidence
    swings count even when the text position is similar.
    """
    if prev is None:
        return debater_id, 1.0

    prev_position = str(prev.get("position", ""))
    curr_position = str(curr.get("position", ""))

    prev_emb, curr_emb = await asyncio.gather(
        embedder.embed(prev_position),
        embedder.embed(curr_position),
    )

    # FailOpenEmbedder returns [] if the provider is unavailable.
    # Treat that as "we cannot tell" → max distance (force continue).
    if not prev_emb or not curr_emb:
        text_distance = 1.0
    else:
        text_distance = _cosine_distance(prev_emb, curr_emb)

    prev_conf = float(prev.get("confidence", 0.5))
    curr_conf = float(curr.get("confidence", 0.5))
    conf_delta = abs(curr_conf - prev_conf)

    return debater_id, max(text_distance, conf_delta)


def _has_active_revision(turn: dict[str, Any]) -> bool:
    decision = turn.get("decision")
    return decision in {"CONCEDE_PARTIAL", "CONCEDE_FULL", "REFINE"}


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance ∈ [0, 2]; clamped to [0, 1] for the threshold."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    cosine = dot / (norm_a * norm_b)
    return max(0.0, 1.0 - cosine)


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "compute_stance_delta",
    "description": (
        "Deterministic stance-delta computation for the Think Tank "
        "early-stop check. Returns should_continue=False when the "
        "aggregate embedding distance + confidence change between two "
        "rounds is below threshold AND no debater issued REFINE/"
        "CONCEDE_PARTIAL/CONCEDE_FULL."
    ),
    "category": "workflow",
    "deps": [],
}

_impl = compute_stance_delta
