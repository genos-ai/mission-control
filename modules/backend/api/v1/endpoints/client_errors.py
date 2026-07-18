"""
Client Error Reporting Endpoint.

Receives error reports from frontend clients and logs them
to var/logs/system.jsonl with source="web" for unified troubleshooting.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import RequestId
from modules.backend.core.logging import get_logger, log_with_source
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.client_error import ClientErrorReceived, ClientErrorReport

router = APIRouter()

logger = get_logger(__name__)


@router.post(
    "", response_model=ApiResponse[ClientErrorReceived], summary="Report a client-side error"
)
async def report_client_error(
    body: ClientErrorReport,
    request_id: RequestId,
) -> ApiResponse:
    """
    Receive a frontend error report and log it server-side.

    This allows all errors (backend + frontend) to appear in
    var/logs/system.jsonl for unified troubleshooting.
    """
    log_with_source(
        logger,
        "web",
        "error",
        f"Client error: {body.message}",
        stack=body.stack,
        component_stack=body.component_stack,
        url=body.url,
        user_agent=body.user_agent,
        client_timestamp=body.timestamp,
    )

    return ApiResponse(
        success=True,
        data=ClientErrorReceived(),
        metadata={"request_id": request_id},
    )
