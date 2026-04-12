"""
Agent Endpoints.

REST API for agent interaction: chat, streaming, and registry listing.
All chat goes through sessions. Auto-creates ephemeral session when none provided.
Multi-agent missions go through the missions API, not here.
"""

from pydantic import BaseModel, Field

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.logging import get_logger
from modules.backend.schemas.base import ApiResponse

logger = get_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for agent chat."""

    message: str = Field(
        ...,
        min_length=1,
        description="User message to send to the agent",
    )
    mission_id: str = Field(
        ...,
        description="Mission ID. Every conversation must be scoped to a mission.",
    )
    agent: str | None = Field(
        default=None,
        description="Target a specific agent by name, bypassing routing.",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID. Auto-created if omitted.",
    )


class ChatResponse(BaseModel):
    """Response from an agent."""

    agent_name: str
    output: str
    session_id: str | None = None


class AgentInfo(BaseModel):
    """Agent registry entry."""

    agent_name: str
    description: str
    keywords: list[str]
    tools: list[str]


@router.post(
    "/chat",
    response_model=ApiResponse[ChatResponse],
    summary="Chat with an agent",
    description="Send a message to an agent via single-agent routing. Auto-creates a session if none provided.",
)
async def agent_chat(
    data: ChatRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse[ChatResponse]:
    """Send a message to an agent. Auto-creates ephemeral session when no session_id provided."""
    from modules.backend.agents.mission_control.mission_control import collect
    from modules.backend.services.session import SessionService

    service = SessionService(db)
    session_id = await service.ensure_session(
        data.session_id, agent_id=data.agent, goal=data.message,
    )

    result = await collect(
        session_id,
        data.message,
        mission_id=data.mission_id,
        session_service=service,
        db_session=db,
    )

    return ApiResponse(
        data=ChatResponse(
            agent_name=result.get("agent_name", ""),
            output=result.get("output", ""),
            session_id=session_id,
        ),
    )


@router.post(
    "/chat/stream",
    response_model=ApiResponse,
    summary="Chat with an agent",
    description=(
        "Send a message to an agent. The agent turn runs as a durable "
        "Temporal workflow. Returns immediately — events stream via "
        "GET /streams/runs/{session_id}."
    ),
)
async def agent_chat_stream(
    data: ChatRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Start an agent chat turn via Temporal."""
    from modules.backend.core.config import get_app_config
    from modules.backend.services.session import SessionService
    from modules.backend.temporal.chat_models import ChatTurnInput
    from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
    from modules.backend.temporal.client import get_temporal_client

    service = SessionService(db)
    session_id = await service.ensure_session(
        data.session_id, agent_id=data.agent, goal=data.message,
    )

    temporal_config = get_app_config().temporal
    client = await get_temporal_client()
    input_data = ChatTurnInput(
        session_id=session_id,
        mission_id=data.mission_id,
        message=data.message,
        sender_id=None,
        channel="api",
    )

    import uuid
    workflow_id = f"chat-turn-{session_id}-{uuid.uuid4().hex[:8]}"

    await client.start_workflow(
        ChatTurnWorkflow.run,
        input_data,
        id=workflow_id,
        task_queue=temporal_config.task_queue,
    )

    return ApiResponse(
        success=True,
        data={
            "session_id": session_id,
            "workflow_id": workflow_id,
            "status": "accepted",
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/registry",
    response_model=ApiResponse[list[AgentInfo]],
    summary="List available agents",
    description="Returns all enabled agents with their capabilities and keywords.",
)
async def agent_registry(
    request_id: RequestId,
) -> ApiResponse[list[AgentInfo]]:
    """List all available agents."""
    from modules.backend.agents.mission_control.mission_control import list_agents

    agents = list_agents()
    return ApiResponse(
        data=[AgentInfo(**a) for a in agents],
    )
