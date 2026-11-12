"""Repair inflated failure learnings (Plan 88, 88.3.4 review follow-up)

Before 88.3.4 the extractor added +1 to occurrence_count on every sweep, keyed
dedup on (agent, kind) and wrote failure tiers in the "FailureTier.X" form.
Data-only repair of ACTIVE failure_pattern and retry_strategy rows:

1. evidence.failure_tiers entries are normalised to the FailureTier value.
2. Rows sharing (mission_id, agent, tier) after normalisation are merged into
   the row find_failure_learning would return (newest updated_at). The others
   are marked superseded. Evidence is unioned in that order; kind is
   retry_strategy when any row of the group is, since success is monotonic.
3. occurrence_count = len(evidence.task_attempt_ids); confidence and title are
   re-derived from it with the 88.3.4 formulas.

Rows with no failure tier or no agent get only step 3's count and confidence.
Downgrade is a no-op: inflated counts and legacy tier strings are not
restorable and nothing reads them.

Revision ID: plan88_003a
Revises: plan88_003
Create Date: 2026-11-12
"""

import math
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from modules.backend.core.logging import get_logger

revision: str = "plan88_003a"
down_revision: Union[str, None] = "plan88_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = get_logger(__name__)

# Frozen at plan88_003a: FailureTier names and values, LearningKind and
# LearningStatus values, and MissionLearningExtractor formulas.
_LEGACY_TIERS = {
    "FailureTier.TIER_1_STRUCTURAL": "tier_1_structural",
    "FailureTier.TIER_2_QUALITY": "tier_2_quality",
    "FailureTier.TIER_3_INTEGRATION": "tier_3_integration",
    "FailureTier.AGENT_ERROR": "agent_error",
    "FailureTier.TIMEOUT": "timeout",
}
_FAILURE_PATTERN = "failure_pattern"
_RETRY_STRATEGY = "retry_strategy"
_ACTIVE = "active"
_SUPERSEDED = "superseded"
_EVIDENCE_ID_KEYS = ("task_attempt_ids", "execution_ids", "failure_tiers", "artifact_ids")
_RETRY_FALLBACK_RECOMMENDATION = (
    "Agent eventually succeeded — review the successful attempt for the working approach."
)
_FAILURE_RECOMMENDATION = "Recurring failure pattern — consider a different agent or approach."

_SELECT_SQL = (
    sa.text(
        "SELECT id, mission_id, kind, title, recommendation, evidence, agent_names, "
        "confidence, occurrence_count, platform_promoted, promoted_at, promoted_by "
        "FROM mission_learnings WHERE status = :active AND kind IN (:fp, :rs) "
        "ORDER BY updated_at DESC, created_at DESC, id DESC"
    )
    .bindparams(active=_ACTIVE, fp=_FAILURE_PATTERN, rs=_RETRY_STRATEGY)
    .columns(evidence=sa.JSON, agent_names=sa.JSON)
)

_UPDATE_SQL = sa.text(
    "UPDATE mission_learnings SET kind = :kind, title = :title, "
    "recommendation = :recommendation, evidence = :evidence, confidence = :confidence, "
    "occurrence_count = :occurrence_count, platform_promoted = :platform_promoted, "
    "promoted_at = :promoted_at, promoted_by = :promoted_by, updated_at = now() "
    "WHERE id = :id"
).bindparams(sa.bindparam("evidence", type_=sa.JSON))

_SUPERSEDE_SQL = sa.text(
    "UPDATE mission_learnings SET status = :superseded, updated_at = now() WHERE id = :id"
).bindparams(superseded=_SUPERSEDED)


def _confidence(count: int) -> float:
    return min(0.95, 0.3 + 0.15 * count)


def _title(agent: str, tier: str, count: int) -> str:
    return f"{agent} — {tier} failures ({count}x)"


def _normalise_evidence(evidence: dict | None) -> dict:
    evidence = dict(evidence or {})
    tiers = evidence.get("failure_tiers")
    if tiers:
        evidence["failure_tiers"] = list(dict.fromkeys(_LEGACY_TIERS.get(t, t) for t in tiers))
    return evidence


def _union(rows_evidence: list[dict]) -> dict:
    merged = dict(rows_evidence[0])
    for evidence in rows_evidence[1:]:
        for key in _EVIDENCE_ID_KEYS:
            if evidence.get(key):
                merged[key] = list(dict.fromkeys(merged.get(key, []) + evidence[key]))
    for key in _EVIDENCE_ID_KEYS:
        if key in merged:
            merged[key] = list(dict.fromkeys(merged[key]))
    return merged


def _group_key(row, evidence: dict) -> tuple | None:
    agents = row.agent_names or []
    tiers = evidence.get("failure_tiers") or []
    if not agents or not tiers:
        return None
    return (str(row.mission_id), agents[0], tiers[0])


def _repaired(group: list) -> dict:
    """Merged column values for a group; group[0] is the surviving row."""
    survivor = group[0]
    evidence = _union([_normalise_evidence(r.evidence) for r in group])
    retry_rows = [r for r in group if r.kind == _RETRY_STRATEGY]
    kind = _RETRY_STRATEGY if retry_rows else _FAILURE_PATTERN
    recommendation = survivor.recommendation
    if kind == _RETRY_STRATEGY and survivor.kind != _RETRY_STRATEGY:
        recommendation = retry_rows[0].recommendation
    if kind == _RETRY_STRATEGY and recommendation == _FAILURE_RECOMMENDATION:
        recommendation = _RETRY_FALLBACK_RECOMMENDATION
    promoted = next((r for r in group if r.platform_promoted), None)
    count = len(evidence.get("task_attempt_ids", []))
    key = _group_key(survivor, evidence)
    return {
        "id": survivor.id,
        "kind": kind,
        "title": _title(key[1], key[2], count) if key else survivor.title,
        "recommendation": recommendation,
        "evidence": evidence,
        "confidence": _confidence(count),
        "occurrence_count": count,
        "platform_promoted": promoted is not None,
        "promoted_at": promoted.promoted_at if promoted else None,
        "promoted_by": promoted.promoted_by if promoted else None,
    }


def _unchanged(row, values: dict) -> bool:
    return (
        row.kind == values["kind"]
        and row.title == values["title"]
        and row.recommendation == values["recommendation"]
        and (row.evidence or {}) == values["evidence"]
        and math.isclose(float(row.confidence), values["confidence"], abs_tol=1e-6)
        and row.occurrence_count == values["occurrence_count"]
        and row.platform_promoted == values["platform_promoted"]
    )


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(_SELECT_SQL).fetchall()

    groups: dict[tuple, list] = {}
    for row in rows:
        key = _group_key(row, _normalise_evidence(row.evidence))
        groups.setdefault(key if key else ("ungrouped", str(row.id)), []).append(row)

    repaired = 0
    superseded = 0
    for group in groups.values():
        values = _repaired(group)
        if not _unchanged(group[0], values):
            conn.execute(_UPDATE_SQL, values)
            repaired += 1
        for loser in group[1:]:
            conn.execute(_SUPERSEDE_SQL, {"id": loser.id})
            superseded += 1

    logger.info(
        "plan88_003a: failure learnings repaired",
        extra={"scanned": len(rows), "repaired": repaired, "superseded": superseded},
    )


def downgrade() -> None:
    # Data repair only; the inflated counts and legacy tier strings are not restorable.
    pass
