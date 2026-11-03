"""
Security Utilities.

Authentication, authorization, and security helpers.
"""

from datetime import timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from modules.backend.core.config import get_app_config, get_settings
from modules.backend.core.exceptions import AuthenticationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    settings = get_settings()
    jwt_config = get_app_config().security.jwt
    to_encode = data.copy()

    issued_at = utc_now()
    if expires_delta:
        expire = issued_at + expires_delta
    else:
        expire = issued_at + timedelta(minutes=jwt_config.access_token_expire_minutes)

    to_encode.update(
        {"iat": issued_at, "exp": expire, "type": "access", "aud": jwt_config.audience}
    )
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=jwt_config.algorithm)
    return encoded_jwt


def create_refresh_token(data: dict[str, Any]) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Payload data to encode

    Returns:
        Encoded JWT refresh token
    """
    settings = get_settings()
    jwt_config = get_app_config().security.jwt
    to_encode = data.copy()
    issued_at = utc_now()
    expire = issued_at + timedelta(days=jwt_config.refresh_token_expire_days)
    to_encode.update(
        {"iat": issued_at, "exp": expire, "type": "refresh", "aud": jwt_config.audience}
    )
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=jwt_config.algorithm)
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        AuthenticationError: If token is invalid or expired
    """
    settings = get_settings()
    jwt_config = get_app_config().security.jwt
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[jwt_config.algorithm],
            audience=jwt_config.audience,
        )
        return payload
    except JWTError as e:
        logger.warning("Token decode failed", extra={"error": str(e)})
        raise AuthenticationError("Invalid or expired token")


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (full_key, hashed_key)
        - full_key: Show to user once
        - hashed_key: Store in database
    """
    import secrets

    # Generate 32-byte random key
    random_part = secrets.token_urlsafe(32)
    full_key = f"app_{random_part}"

    # Hash for storage
    hashed_key = hash_password(full_key)

    return full_key, hashed_key


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """Verify an API key against its hash."""
    return verify_password(plain_key, hashed_key)


# ── Role-based authorization ─────────────────────────────────────────


def check_role_level(user_role: str, minimum_role: str) -> bool:
    """Check if a user role meets the minimum required level.

    Reads role definitions from security.yaml config.

    Args:
        user_role: The user's assigned role name.
        minimum_role: The minimum required role name.

    Returns:
        True if user_role level >= minimum_role level.

    Raises:
        ValueError: If minimum_role is not a recognized role name.
    """
    roles = get_app_config().security.roles
    min_def = roles.get(minimum_role)
    if not min_def:
        raise ValueError(f"Unknown role: {minimum_role}")

    actual_def = roles.get(user_role)
    actual_level = actual_def.level if actual_def else 0
    return actual_level >= min_def.level


def resolve_user_role_from_config(user_id: int) -> str:
    """Resolve a Telegram/external user ID to a role name from config.

    Reads security.user_roles mapping from security.yaml.
    Falls back to 'viewer' if no explicit mapping exists.

    Args:
        user_id: External user identifier (e.g. Telegram user ID).

    Returns:
        Role name string.
    """
    security = get_app_config().security
    user_roles = {int(uid): role for uid, role in security.user_roles.items()}
    return user_roles.get(user_id, "viewer")
