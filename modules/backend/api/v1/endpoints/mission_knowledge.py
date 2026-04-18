"""
Mission Knowledge API — mission-scoped knowledge endpoints.

GET /missions/{id}/knowledge       — unified knowledge view
GET /missions/{id}/learnings       — list learnings
GET /missions/{id}/learnings/{lid} — learning detail
GET /missions/{id}/learnings/{lid}/evidence — paged evidence
GET /missions/{id}/learnings/{lid}/similar  — vector-similar entries
GET /missions/{id}/intent          — current intent
GET /missions/{id}/intent/history  — revision timeline
POST /missions/{id}/intent         — create intent revision
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import CurrentUser, DbSession
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_intent import (
    MissionIntentCreate,
    MissionIntentListResponse,
    MissionIntentResponse,
)
from modules.backend.schemas.mission_learning import (
    MissionLearningListResponse,
    MissionLearningResponse,
)
from modules.backend.services.knowledge import KnowledgeService
from modules.backend.services.mission_intent import MissionIntentService
from modules.backend.services.mission_learning import MissionLearningService

router = APIRouter()


# ------------------------------------------------------------------
# Knowledge unified view
# ------------------------------------------------------------------


@router.get("/missions/{mission_id}/knowledge")
async def get_mission_knowledge(
    mission_id: str,
    db: DbSession,
    user: CurrentUser,
    domain_tags: str | None = Query(None, description="Comma-separated domain tags"),
) -> ApiResponse:
    """Unified knowledge view for a mission."""
    tags = [t.strip() for t in domain_tags.split(",")] if domain_tags else None
    svc = KnowledgeService(db)
    result = await svc.get_mission_knowledge(mission_id, domain_tags=tags)
    return ApiResponse(data=result)


# ------------------------------------------------------------------
# Learnings
# ------------------------------------------------------------------


@router.get("/missions/{mission_id}/learnings")
async def list_mission_learnings(
    mission_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = Query(None),
    domain_tags: str | None = Query(None, description="Comma-separated domain tags"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """List learnings for a mission."""
    tags = [t.strip() for t in domain_tags.split(",")] if domain_tags else None
    svc = MissionLearningService(db)
    learnings = await svc.list_by_mission(
        mission_id, kind=kind, domain_tags=tags, limit=limit, offset=offset,
    )
    total = await svc.count_by_mission(mission_id)
    return ApiResponse(data={
        "items": [MissionLearningResponse.model_validate(l).model_dump() for l in learnings],
        "total": total,
    })


@router.get("/missions/{mission_id}/learnings/{learning_id}")
async def get_learning_detail(
    mission_id: str,
    learning_id: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """Get a single learning with evidence."""
    svc = MissionLearningService(db)
    learning = await svc.get_by_id(learning_id)
    return ApiResponse(data=MissionLearningResponse.model_validate(learning))


@router.get("/missions/{mission_id}/learnings/{learning_id}/evidence")
async def get_learning_evidence(
    mission_id: str,
    learning_id: str,
    db: DbSession,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """Paged evidence for a learning entry."""
    svc = MissionLearningService(db)
    learning = await svc.get_by_id(learning_id)
    evidence = learning.evidence or {}

    # Paginate each evidence list
    paginated = {}
    total = 0
    for key, ids in evidence.items():
        if isinstance(ids, list):
            total += len(ids)
            paginated[key] = ids[offset: offset + limit]
        else:
            paginated[key] = ids

    return ApiResponse(data={
        "evidence": paginated,
        "evidence_total": total,
        "offset": offset,
        "limit": limit,
    })


@router.get("/missions/{mission_id}/learnings/{learning_id}/similar")
async def get_similar_learnings(
    mission_id: str,
    learning_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(10, ge=1, le=50),
) -> ApiResponse:
    """Find vector-similar entries to this learning."""
    svc = KnowledgeService(db)
    entries = await svc.similar("mission_learnings", learning_id, limit=limit)
    return ApiResponse(data=[e.model_dump() for e in entries])


# ------------------------------------------------------------------
# Intent
# ------------------------------------------------------------------


@router.get("/missions/{mission_id}/intent")
async def get_current_intent(
    mission_id: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """Get the current intent for a mission."""
    svc = KnowledgeService(db)
    intent = await svc.get_current_intent(mission_id)
    return ApiResponse(data=intent)


@router.get("/missions/{mission_id}/intent/history")
async def list_intent_revisions(
    mission_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """List intent revision history, newest first."""
    svc = MissionIntentService(db)
    revisions = await svc.list_revisions(mission_id, limit=limit, offset=offset)
    total = await svc.count_revisions(mission_id)
    return ApiResponse(data={
        "items": [MissionIntentResponse.model_validate(r).model_dump() for r in revisions],
        "total": total,
    })


@router.post("/missions/{mission_id}/intent")
async def create_intent_revision(
    mission_id: str,
    body: MissionIntentCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """Create a new intent revision."""
    svc = MissionIntentService(db)
    intent = await svc.create_intent(
        mission_id,
        body.intent,
        scope=body.scope,
        source=body.source,
        reason=body.reason,
        agent_id=body.agent_id,
        session_id=body.session_id,
    )
    await db.commit()

    if intent is None:
        return ApiResponse(data={"status": "dedup", "message": "Identical to current intent"})

    return ApiResponse(data=MissionIntentResponse.model_validate(intent))
