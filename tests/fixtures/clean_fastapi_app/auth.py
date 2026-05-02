"""Clean auth — secret from environment, not hardcoded."""

import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

JWT_SECRET = os.environ["JWT_SECRET"]  # fails fast if not set
JWT_ALGORITHM = "HS256"

security = HTTPBearer()


async def get_current_user(token: str = Depends(security)) -> dict:
    try:
        return jwt.decode(token.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
