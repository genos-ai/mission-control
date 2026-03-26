"""
API Version 1 Router.

Aggregates all v1 endpoint routers.
"""

from fastapi import APIRouter

from modules.backend.api.v1.endpoints import (
    admin,
    admin_users,
    agents,
    auth,
    catalog,
    client_errors,
    executions,
    missions,
    notes,
    sessions,
    streams,
    workflows,
    workshop,
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

# Workshop (single-agent sandbox) endpoints
router.include_router(workshop.router, prefix="/workshop", tags=["workshop"])

# Auth endpoints (login, token refresh, API key management)
router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Admin endpoints (protected by admin role)
router.include_router(admin.router, prefix="/admin", tags=["admin"])

# Admin user management endpoints
router.include_router(admin_users.router, prefix="/admin/users", tags=["admin"])

# SSE streaming endpoints (notifications, run events)
router.include_router(streams.router, prefix="/streams", tags=["streams"])

# Client error reporting (frontend → server logs)
router.include_router(client_errors.router, prefix="/client-errors", tags=["client-errors"])
