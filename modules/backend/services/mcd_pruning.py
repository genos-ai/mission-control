"""
MCD pruning helpers (Plan 88, 88.3.2 and 88.3.3).

Pure functions over the Mission Context Document plus the two archive writers
that move pruned decisions and milestones into their history tables. The size
measure here is the one the MCD cap compares against: UTF-8 bytes of the JSON
serialisation. Imports repositories and core only, never another service, so
both SummarizationService and the write-path compactor can use it.
"""

import json

from modules.backend.core.utils import utc_now
from modules.backend.models.mission_history import DecisionStatus
from modules.backend.repositories.mission_history import (
    MilestoneSummaryRepository,
    MissionDecisionRepository,
)


def mcd_size_bytes(value: object) -> int:
    """UTF-8 byte length of the JSON serialisation of value."""
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def split_decisions_by_age(
    decisions: list[dict], cutoff_date: str
) -> tuple[list[dict], list[dict]]:
    """Returns (keep, archive). A decision is archived when its date sorts before cutoff_date."""
    keep: list[dict] = []
    archive: list[dict] = []
    for d in decisions:
        if d.get("date", "") < cutoff_date:
            archive.append(d)
        else:
            keep.append(d)
    return keep, archive


def split_milestones(milestones: list, keep_recent: int) -> tuple[list, list]:
    """Returns (milestones[:keep_recent], milestones[keep_recent:]); newest first."""
    return milestones[:keep_recent], milestones[keep_recent:]


async def archive_decision_rows(
    repo: MissionDecisionRepository, mission_id: str, decisions: list[dict]
) -> None:
    """One MissionDecision row per decision."""
    for d in decisions:
        await repo.create(
            mission_id=mission_id,
            decision_id=d.get("id", ""),
            domain=d.get("domain", "general"),
            decision=d.get("decision", ""),
            rationale=d.get("rationale", ""),
            made_by=d.get("made_by", "unknown"),
            execution_id=d.get("execution_id"),
            status=DecisionStatus.ACTIVE,
        )


async def archive_milestone_rows(
    repo: MilestoneSummaryRepository, mission_id: str, milestones: list
) -> None:
    """One MilestoneSummary row for the batch."""
    await repo.create(
        mission_id=mission_id,
        title=f"Milestones batch ({len(milestones)} items)",
        summary="; ".join(m if isinstance(m, str) else str(m) for m in milestones),
        execution_ids=[],
        key_outcomes={"milestones": milestones},
        domain_tags=[],
        period_end=utc_now().replace(microsecond=0).isoformat(),
    )
