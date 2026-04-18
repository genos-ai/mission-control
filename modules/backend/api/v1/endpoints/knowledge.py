"""
Platform Knowledge API — sysadmin-scoped cross-mission endpoints.

GET /knowledge/search       — unified search (structured | hybrid | semantic)
GET /knowledge/similar/{id} — vector-similar entries platform-wide
GET /knowledge/learnings    — platform-promoted learnings
GET /knowledge/decisions    — cross-mission decisions
GET /knowledge/milestones   — cross-mission milestones
GET /knowledge/tags         — taxonomy + suggestion log

All endpoints require admin role.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import AdminRole, DbSession
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_learning import MissionLearningListResponse, MissionLearningResponse
from modules.backend.services.knowledge import KnowledgeService
from modules.backend.services.mission_learning import MissionLearningService

router = APIRouter()


@router.get("/knowledge/search")
async def search_knowledge(
    db: DbSession,
    admin: AdminRole,
    q: str = Query("", description="Search query text"),
    tags: str | None = Query(None, description="Comma-separated domain tags"),
    kinds: str | None = Query(None, description="Comma-separated kinds: learning,decision,milestone"),
    mission_id: str | None = Query(None),
    platform_only: bool = Query(False),
    mode: str = Query("hybrid", description="structured | hybrid | semantic"),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """Search across all knowledge surfaces."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None

    svc = KnowledgeService(db)
    entries = await svc.search(
        q, mission_id=mission_id, platform_only=platform_only,
        kinds=kind_list, domain_tags=tag_list, mode=mode, limit=limit,
    )
    return ApiResponse(data=[e.model_dump() for e in entries])


@router.get("/knowledge/similar/{source_table}/{source_id}")
async def get_similar_entries(
    source_table: str,
    source_id: str,
    db: DbSession,
    admin: AdminRole,
    limit: int = Query(10, ge=1, le=50),
) -> ApiResponse:
    """Find entries similar to the given one by vector distance."""
    svc = KnowledgeService(db)
    entries = await svc.similar(source_table, source_id, limit=limit)
    return ApiResponse(data=[e.model_dump() for e in entries])


@router.get("/knowledge/learnings")
async def list_platform_learnings(
    db: DbSession,
    admin: AdminRole,
    kind: str | None = Query(None),
    domain_tags: str | None = Query(None, description="Comma-separated domain tags"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """List platform-promoted learnings across all missions."""
    tags = [t.strip() for t in domain_tags.split(",")] if domain_tags else None
    svc = MissionLearningService(db)
    learnings = await svc.list_platform(kind=kind, domain_tags=tags, limit=limit, offset=offset)
    return ApiResponse(data={
        "items": [MissionLearningResponse.model_validate(l).model_dump() for l in learnings],
        "total": len(learnings),
    })


@router.get("/knowledge/decisions")
async def list_platform_decisions(
    db: DbSession,
    admin: AdminRole,
    domain: str | None = Query(None),
    mission_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """List archived decisions across missions."""
    svc = KnowledgeService(db)
    decisions = await svc.list_decisions(
        mission_id=mission_id, domain=domain, limit=limit,
    )
    return ApiResponse(data=decisions)


@router.get("/knowledge/milestones")
async def list_platform_milestones(
    db: DbSession,
    admin: AdminRole,
    mission_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """List milestone summaries across missions."""
    svc = KnowledgeService(db)
    milestones = await svc.list_milestones(mission_id=mission_id, limit=limit)
    return ApiResponse(data=milestones)


@router.get("/knowledge/tags")
async def list_knowledge_tags(
    db: DbSession,
    admin: AdminRole,
) -> ApiResponse:
    """List the current domain tag taxonomy."""
    from modules.backend.core.domain_tags import CROSS_CUTTING_TAGS
    return ApiResponse(data={
        "cross_cutting_tags": sorted(CROSS_CUTTING_TAGS),
        "total": len(CROSS_CUTTING_TAGS),
    })
