"""
Mission notification recipient endpoints (Plan 88 step 88.4.4, contract 3.5.3).

    GET    /missions/{id}/notification-recipients         list (mission access)
    POST   /missions/{id}/notification-recipients         add by email (mission owner)
    DELETE /missions/{id}/notification-recipients/{rid}   remove (mission owner)

A recipient is scoped by mission (3.0.2): another mission's recipient is 404.
``channel`` and ``kinds`` use lowercase values.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_existing_mission_access,
    require_mission_owner,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.notification import (
    NotificationRecipientCreate,
    NotificationRecipientListResponse,
)
from modules.backend.services.notification import NotificationService

router = APIRouter()


@router.get(
    "/{mission_id}/notification-recipients",
    response_model=ApiResponse,
    summary="List the mission's notification recipients",
)
async def list_recipients(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Every recipient with the user's email, channel and subscribed kinds."""
    await require_existing_mission_access(db, mission_id, current_user)
    recipients = await NotificationService(db).list_recipients(mission_id)
    return ApiResponse(
        success=True,
        data=NotificationRecipientListResponse(recipients=recipients).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/notification-recipients",
    response_model=ApiResponse,
    summary="Add a notification recipient",
)
async def add_recipient(
    mission_id: str,
    data: NotificationRecipientCreate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Subscribe the mission owner or a member; kinds default to notifications.default_kinds."""
    await require_mission_owner(db, mission_id, current_user)
    recipient = await NotificationService(db).add_recipient(mission_id, data, current_user.id)
    return ApiResponse(
        success=True,
        data=recipient.model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/notification-recipients/{recipient_id}",
    response_model=ApiResponse,
    summary="Remove a notification recipient",
)
async def remove_recipient(
    mission_id: str,
    recipient_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Remove a recipient of this mission."""
    await require_mission_owner(db, mission_id, current_user)
    await NotificationService(db).remove_recipient(mission_id, recipient_id, current_user.id)
    return ApiResponse(
        success=True,
        data={"id": recipient_id},
        metadata={"request_id": request_id},
    )
