"""
Idempotency key support for mutating API endpoints.

Clients send an `Idempotency-Key: <uuid>` header on POST requests.
The server caches the response in Redis. On replay, the cached
response is returned immediately — the operation is not re-executed.

Pattern: P6 from the reference architecture — Idempotency is required
for any operation that is expensive to duplicate (agent executions,
resource creation) and that clients may retry on network timeout.

Usage in an endpoint:

    async def create_resource(
        ...
        idempotency: Idempotency,
    ) -> ApiResponse:
        if idempotency:
            cached = await idempotency.get_cached_response()
            if cached:
                return ApiResponse(**cached)

        # ... create the resource ...
        response = ApiResponse(success=True, data=result)

        if idempotency:
            await idempotency.cache_response(response.model_dump())

        return response

Key format:  idempotency:{raw_key}
TTL:         24 hours (configurable)
Header name: Idempotency-Key
"""

from __future__ import annotations

import json

from redis.asyncio import Redis as AsyncRedis

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "idempotency"
_DEFAULT_TTL = 86400  # 24 hours


class IdempotencyGuard:
    """Per-request idempotency checker — holds key + Redis connection.

    Returned by the `get_idempotency` dependency when an Idempotency-Key
    header is present. None is returned when the header is absent
    (operation proceeds normally, no caching).
    """

    def __init__(self, redis: AsyncRedis, key: str) -> None:
        self._redis = redis
        self._key = f"{_KEY_PREFIX}:{key}"

    async def get_cached_response(self) -> dict | None:
        """Return the cached response dict if this key has been seen before.

        Returns None on cache miss or any Redis error (fail open — better
        to re-execute than to block on a Redis outage).
        """
        try:
            value = await self._redis.get(self._key)
            if value:
                logger.debug(
                    "Idempotency cache hit",
                    extra={"key": self._key},
                )
                return json.loads(value)
        except Exception:
            logger.warning(
                "Idempotency Redis read failed — proceeding without cache",
                extra={"key": self._key},
                exc_info=True,
            )
        return None

    async def cache_response(
        self,
        response_data: dict,
        ttl: int = _DEFAULT_TTL,
    ) -> None:
        """Cache a response for this idempotency key.

        Best-effort — a Redis write failure does not break the response.
        """
        try:
            await self._redis.set(
                self._key,
                json.dumps(response_data, default=str),
                ex=ttl,
            )
            logger.debug(
                "Idempotency response cached",
                extra={"key": self._key, "ttl": ttl},
            )
        except Exception:
            logger.warning(
                "Idempotency Redis write failed — response not cached",
                extra={"key": self._key},
                exc_info=True,
            )
