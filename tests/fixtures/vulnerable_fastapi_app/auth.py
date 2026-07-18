"""Deliberately weak authentication for WASA testing.

CWE-798: JWT signed with weak hardcoded secret from config.py.
"""

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

from tests.fixtures.vulnerable_fastapi_app.config import JWT_ALGORITHM, JWT_SECRET

security = HTTPBearer()


async def get_current_user(token: str = Depends(security)) -> dict:
    """Decode JWT — uses weak hardcoded secret."""
    try:
        payload = jwt.decode(
            token.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
