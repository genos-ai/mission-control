"""
Mission Artifacts API endpoints (Plan 43).

Durable artifact retrieval for a mission. Dual-write lifecycle:
``persist_mission_results`` writes the row at run completion, the live
``MissionArtifactFoundEvent`` SSE event still fires for in-flight
preview, and the frontend invalidates this query on that event to pick
up newly-persisted rows.

Read-only for now — agents produce artifacts via the dispatch loop,
not through a POST API. If a client needs to upload an artifact
directly (attach a pre-made report to a mission) that's a v2
capability and requires the file-storage decision parked in
Plan 43 §3.7.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_artifact import MissionArtifactResponse
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_artifact import MissionArtifactService

router = APIRouter()


async def _require_mission_access(
    db, mission_id: str, current_user,
) -> None:
    """Admin, mission owner, or any mission member can read artifacts.

    Mirrors the access-check pattern used in missions_plan.py and
    missions.py — mission-scoped resources all gate the same way.
    """
    mission_service = MissionService(db)
    mission = await mission_service.get_mission(mission_id)
    if current_user.has_role("admin"):
        return
    if mission.owner_id == current_user.id:
        return
    if any(m.user_id == current_user.id for m in mission.members):
        return
    raise AuthorizationError("You don't have access to this mission")


@router.get(
    "/{mission_id}/artifacts",
    response_model=ApiResponse,
    summary="List persisted artifacts for a mission",
)
async def list_mission_artifacts(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    limit: int = Query(
        50, ge=1, le=500,
        description="Maximum artifacts to return (newest first). Caps at 500.",
    ),
    artifact_type: str | None = Query(
        None,
        description=(
            "Exact-match filter on artifact_type "
            "(report | finding | code | data | file). "
            "Omit for all types."
        ),
    ),
) -> ApiResponse:
    """Return the persisted artifacts for a mission, newest first.

    Pagination is limit-only for v1 — expected volume per mission is
    small (tens to low hundreds) and the default frontend cap is 50.
    Larger missions can bump the limit up to 500.

    The ``storage_url`` field is always null in v1 (text artifacts
    only); it's reserved for a future file-artifact extension point.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionArtifactService(db)
    artifacts = await service.list_for_mission(
        mission_id=mission_id,
        limit=limit,
        artifact_type=artifact_type,
    )

    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "artifacts": [
                MissionArtifactResponse.model_validate(a).model_dump(mode="json")
                for a in artifacts
            ],
            "count": len(artifacts),
        },
        metadata={"request_id": request_id},
    )
