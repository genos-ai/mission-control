"""Deliberately vulnerable FastAPI app for WASA SAST testing.

Contains known vulnerabilities that security scanners should detect:
- SQL injection via f-string in text() (CWE-89)
- Hardcoded API key (CWE-798)
- IDOR on /api/users/{id} with no ownership check (CWE-639)
- Weak JWT secret (CWE-798)

Expected: >= 5 TRUE_POSITIVE findings across SAST tools.
DO NOT deploy this application. It exists solely as a test fixture.
"""

from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.vulnerable_fastapi_app.auth import get_current_user
from tests.fixtures.vulnerable_fastapi_app.config import API_KEY
from tests.fixtures.vulnerable_fastapi_app.database import get_db

app = FastAPI(title="Vulnerable Test App")


# CWE-89: SQL injection via f-string interpolation in text()
@app.get("/api/users/{user_id}")
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    # VULNERABILITY: f-string in raw SQL — no parameterisation
    query = text(f"SELECT * FROM users WHERE id = {user_id}")
    result = await db.execute(query)
    return result.mappings().first()


# CWE-639: IDOR — no ownership check, any authenticated user can
# access any other user's data by changing the ID parameter
@app.get("/api/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # VULNERABILITY: no check that current_user.id == user_id
    query = text(f"SELECT * FROM profiles WHERE user_id = {user_id}")
    result = await db.execute(query)
    return result.mappings().first()


# CWE-798: API key used directly from hardcoded config
@app.get("/api/external")
async def call_external():
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.example.com/data",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        return resp.json()
