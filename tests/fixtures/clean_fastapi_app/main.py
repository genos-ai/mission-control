"""Deliberately clean FastAPI app — no true-positive findings expected.

Uses: ORM queries only, no hardcoded secrets, all endpoints auth-guarded
with ownership checks, pinned non-vulnerable dependencies, Dockerfile
follows best practices.

Expected: 0 TRUE_POSITIVE after triage.
"""

import os

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.clean_fastapi_app.auth import get_current_user
from tests.fixtures.clean_fastapi_app.database import get_db
from tests.fixtures.clean_fastapi_app.models import User

app = FastAPI(title="Clean Test App")


@app.get("/api/users/me")
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Only returns the authenticated user's own profile."""
    stmt = select(User).where(User.id == current_user["sub"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "email": user.email}


@app.get("/api/users/{user_id}")
async def get_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ownership check: only admins or the user themselves can access."""
    if current_user["sub"] != user_id and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "email": user.email}
