"""
Workshop API Endpoints.

Single-agent testing sandbox. Run agents in isolation with optional
prompt overrides and cached inputs from previous workflow runs.
"""

from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from modules.backend.schemas.base import ApiResponse
from modules.backend.core.dependencies import DbSession, RequestId

router = APIRouter()


class WorkshopRunRequest(BaseModel):
    """Request body for a workshop agent run."""

    inputs: dict[str, Any] | None = Field(
        None, description="Input data to pass to the agent",
    )
    prompt_override: str | None = Field(
        None, description="Temporary system prompt override (not persisted)",
    )
    session_id: str | None = Field(
        None, description="Optional session ID for tracking",
    )
    budget_usd: float | None = Field(
        None, description="Per-run budget override",
    )


@router.post(
    "/{agent_name}/run",
    response_model=ApiResponse,
    summary="Run an agent in workshop mode",
)
async def workshop_run(
    agent_name: str,
    body: WorkshopRunRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Run a single agent in isolation for testing.

    Bypasses the dispatch/planning pipeline. Results are persisted as
    workshop-tagged execution records.
    """
    from modules.backend.services.workshop import WorkshopService

    service = WorkshopService(db)
    result = await service.run_agent(
        agent_name,
        inputs=body.inputs,
        prompt_override=body.prompt_override,
        session_id=body.session_id,
        budget_usd=body.budget_usd,
    )

    return ApiResponse(
        success=True,
        data=result,
        metadata={"request_id": request_id},
    )


@router.get(
    "/{agent_name}/cached-inputs",
    response_model=ApiResponse,
    summary="Get cached inputs from previous runs",
)
async def workshop_cached_inputs(
    agent_name: str,
    db: DbSession,
    request_id: RequestId,
    mission_id: str | None = None,
    limit: int | None = None,
) -> ApiResponse:
    """Retrieve cached outputs from previous successful runs of this agent.

    These can be re-used as inputs for workshop testing.
    """
    from modules.backend.services.workshop import WorkshopService

    service = WorkshopService(db)
    cached = await service.get_cached_inputs(
        agent_name,
        mission_id=mission_id,
        limit=limit,
    )

    return ApiResponse(
        success=True,
        data={"agent_name": agent_name, "cached_inputs": cached},
        metadata={"request_id": request_id},
    )


@router.get(
    "/runs",
    response_model=ApiResponse,
    summary="List workshop runs",
)
async def workshop_list_runs(
    db: DbSession,
    request_id: RequestId,
    agent_name: str | None = None,
    limit: int = 20,
) -> ApiResponse:
    """List execution records from workshop runs."""
    from modules.backend.services.workshop import WorkshopService

    service = WorkshopService(db)
    runs = await service.list_runs(agent_name=agent_name, limit=limit)

    return ApiResponse(
        success=True,
        data={
            "runs": [
                {
                    "id": r.id,
                    "agent_name": r.roster_name,
                    "status": r.status,
                    "cost_usd": r.total_cost_usd,
                    "created_at": r.created_at,
                }
                for r in runs
            ],
            "count": len(runs),
        },
        metadata={"request_id": request_id},
    )
