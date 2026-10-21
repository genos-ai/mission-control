"""
API Version 1 Router.

Aggregates all v1 endpoint routers.
"""

from fastapi import APIRouter, Depends

from modules.backend.api.v1.endpoints import (
    admin,
    admin_users,
    agents,
    attention,
    auth,
    catalog,
    client_errors,
    executions,
    knowledge,
    mission_knowledge,
    missions,
    sessions,
    streams,
    workflows,
    workshop,
)
from modules.backend.core.dependencies import require_scope

router = APIRouter()

# Agent endpoints
router.include_router(agents.router, prefix="/agents", tags=["agents"])

# Agent catalog endpoints
router.include_router(catalog.router, prefix="/catalog/agents", tags=["catalog"])

# Session endpoints
router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

# Execution record endpoints (audit, history, cost)
router.include_router(executions.router, prefix="/executions", tags=["executions"])

# What needs a person across the caller's missions (dashboard, sidebar)
router.include_router(attention.router, prefix="/attention", tags=["attention"])

# Mission management endpoints (CRUD, team, workflows)
router.include_router(missions.router, prefix="/missions", tags=["missions"])

# Workflow template and legacy mission endpoints
router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])

# Workshop (single-agent sandbox) endpoints
router.include_router(workshop.router, prefix="/workshop", tags=["workshop"])

# Auth endpoints (login, token refresh, API key management)
router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Admin endpoints (protected by admin role; require_scope also lets a
# scoped API key be restricted to non-admin use even for an admin user)
router.include_router(
    admin.router,
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_scope("admin"))],
)

# Admin user management endpoints
router.include_router(
    admin_users.router,
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_scope("admin"))],
)

# SSE streaming endpoints (notifications, run events)
router.include_router(streams.router, prefix="/streams", tags=["streams"])

# Client error reporting (frontend → server logs)
router.include_router(client_errors.router, prefix="/client-errors", tags=["client-errors"])

# Knowledge platform (Plan 57) — mission-scoped endpoints (mounted at root for /missions/{id}/... paths)  # noqa: E501
router.include_router(mission_knowledge.router, tags=["knowledge"])

# Knowledge platform (Plan 57) — platform-scoped endpoints (admin only)
router.include_router(knowledge.router, tags=["knowledge"])
