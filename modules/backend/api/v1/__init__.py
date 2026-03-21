"""
API Version 1 Router.

Aggregates all v1 endpoint routers.
"""

from fastapi import APIRouter

from modules.backend.api.v1.endpoints import (
    agents,
    catalog,
    executions,
    missions,
    notes,
    sessions,
    workflows,
)

router = APIRouter()

# Notes endpoints
router.include_router(notes.router, prefix="/notes", tags=["notes"])

# Agent endpoints
router.include_router(agents.router, prefix="/agents", tags=["agents"])

# Agent catalog endpoints
router.include_router(catalog.router, prefix="/catalog/agents", tags=["catalog"])

# Session endpoints
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

# Execution record endpoints (audit, history, cost)
router.include_router(executions.router, prefix="/executions", tags=["executions"])

# Mission management endpoints (CRUD, team, workflows)
router.include_router(missions.router, prefix="/missions", tags=["missions"])

# Workflow template and legacy mission endpoints
router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
