"""
Workflow API endpoints.

Provides endpoints for listing workflows and reading workflow detail.
"""

from fastapi import APIRouter

from modules.backend.core.config import get_app_config
from modules.backend.core.dependencies import CurrentUser, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.workflow import WorkflowService

router = APIRouter()


def _get_workflow_service() -> WorkflowService:
    return WorkflowService()


# ---- Workflow endpoints ----


@router.get("", response_model=ApiResponse, summary="List workflows")
async def list_workflows(
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List available workflows."""
    service = _get_workflow_service()
    workflows = service.list_workflows(enabled_only=enabled_only)

    items = [service.to_list_item(w) for w in workflows]

    return ApiResponse(
        success=True,
        data={"workflows": items},
        metadata={"request_id": request_id, "count": len(items)},
    )


# Declared before "/{workflow_name}", which would otherwise take this path as a workflow name.
@router.get(
    "/editor-defaults",
    response_model=ApiResponse,
    summary="Defaults the workflow editor gives new steps",
)
async def get_editor_defaults(
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """The model alias new LLM-call and decision steps start with (workflows.yaml)."""
    return ApiResponse(
        success=True,
        data={"step_model": get_app_config().workflows.default_step_model},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{workflow_name}",
    response_model=ApiResponse,
    summary="Get workflow detail",
)
async def get_workflow(
    workflow_name: str,
    request_id: RequestId,
) -> ApiResponse:
    """Get a specific workflow with full details."""
    service = _get_workflow_service()
    workflow = service.get_workflow(workflow_name)

    if not workflow:
        raise NotFoundError(
            message=f"Workflow '{workflow_name}' not found",
        )

    return ApiResponse(
        success=True,
        data=service.to_detail(workflow),
        metadata={"request_id": request_id},
    )
