"""
Attention API endpoint.

What needs a person across the missions the caller can see.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.attention import AttentionService

router = APIRouter()


@router.get("", response_model=ApiResponse, summary="What needs attention")
async def get_attention(
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Gates, workflow input, tasks to approve and failed tasks, most urgent first.

    Covers the missions the caller owns or belongs to; an admin gets every open mission.
    `pending_counts` is the number of items per mission, for the sidebar.
    """
    user_id = None if current_user.has_role("admin") else current_user.id
    report = await AttentionService(db).for_user(user_id)
    return ApiResponse(
        success=True,
        data=report.model_dump(mode="json"),
        metadata={"request_id": request_id},
    )
