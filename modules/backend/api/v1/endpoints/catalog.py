"""
Agent Catalog API endpoints.

Browse the global agent registry. Read-only for regular users;
admin endpoints for prompt updates are separate.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.agent_catalog import AgentCatalogDetailResponse, AgentCatalogResponse
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.agent_catalog import AgentCatalogService

router = APIRouter()


@router.get("", response_model=ApiResponse, summary="List catalog agents")
async def list_catalog_agents(
    db: DbSession,
    request_id: RequestId,
    agent_type: str | None = None,
    enabled_only: bool = True,
) -> ApiResponse:
    """List agents in the catalog, optionally filtered by type."""
    service = AgentCatalogService(db)
    agents = await service.list_catalog(
        enabled_only=enabled_only,
        visibility="public",
        agent_type=agent_type,
    )

    items = [AgentCatalogResponse.model_validate(a).model_dump() for a in agents]
    return ApiResponse(
        success=True,
        data={"agents": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{agent_name}",
    response_model=ApiResponse,
    summary="Get agent catalog detail",
)
async def get_catalog_agent(
    agent_name: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get full detail for a catalog agent including system prompt."""
    service = AgentCatalogService(db)
    agent = await service.get_by_name_or_none(agent_name)

    if not agent:
        raise NotFoundError(f"Agent '{agent_name}' not found in catalog")

    detail = AgentCatalogDetailResponse.model_validate(agent)
    return ApiResponse(
        success=True,
        data=detail.model_dump(),
        metadata={"request_id": request_id},
    )
