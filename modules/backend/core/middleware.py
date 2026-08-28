"""
Request Context Middleware.

Middleware for request tracking, timing, source identification, and context propagation.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from modules.backend.core.logging import VALID_SOURCES, bind_context, clear_context, get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds request context to every request.

    Features:
    - Generates or propagates request ID (X-Request-ID header)
    - Extracts source identifier (X-Frontend-ID header)
    - Records request timing (X-Response-Time header)
    - Binds request context to structlog for automatic inclusion in logs
    - Stores context in request.state for access by handlers

    Headers:
    - X-Request-ID: Unique request identifier (generated if not provided)
    - X-Frontend-ID: Source identifier (web, cli, mobile, api, internal, etc.)
    - X-Response-Time: Response duration in milliseconds

    Usage:
        All logs within a request will automatically include:
        - request_id: Unique identifier for the request
        - source: Origin that sent the request
        - method: HTTP method
        - path: Request path

        Access in endpoints:
            request.state.request_id
            request.state.source
            request.state.start_time
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process request with context tracking."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        raw_source = request.headers.get("X-Frontend-ID", "").lower().strip() or None

        if raw_source is not None and raw_source not in VALID_SOURCES:
            logger.warning(
                "Invalid X-Frontend-ID header, ignoring",
                extra={"raw_source": raw_source, "valid_sources": sorted(VALID_SOURCES)},
            )
            raw_source = None

        start_time = utc_now()

        request.state.request_id = request_id
        request.state.source = raw_source
        request.state.start_time = start_time

        clear_context()
        context: dict = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        if raw_source is not None:
            context["source"] = raw_source
        bind_context(**context)

        logger.debug(
            "Request started",
            extra={
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("User-Agent"),
            },
        )

        try:
            response = await call_next(request)

            duration_ms = int((utc_now() - start_time).total_seconds() * 1000)

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms}ms"

            logger.debug(
                "Request completed",
                extra={
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

            return response

        except Exception as exc:
            duration_ms = int((utc_now() - start_time).total_seconds() * 1000)

            logger.error(
                "Request failed with exception",
                extra={
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                },
            )

            raise

        finally:
            clear_context()


def _resolve_rate_limit_key(request: Request) -> str:
    """Identify the caller for rate-limit bucketing without a DB call.

    Order matches get_current_user's resolution order, but stops at
    decoding — no user lookup, so a request that will fail auth further
    down the chain still gets bucketed sanely here (its own key, not
    lumped in with every other unauthenticated caller).
    """
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:]
        try:
            from modules.backend.core import security

            payload = security.decode_token(token)
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            # falling back to IP — an invalid/expired token will fail
            # auth properly at the endpoint; this is only a rate-limit
            # bucketing key, not an auth decision.
            logger.debug("Could not decode bearer token for rate-limit keying")

    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{api_key}"

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies GatewayRateLimiter to auth-sensitive and execution-triggering POSTs.

    Scoped narrowly (Plan 84 §7.1) rather than globally — most read
    endpoints are not meaningful attack surface, and the in-memory
    sliding window is per-process, so it should not be relied on as the
    only defense for every route.

    Correct for the current single-instance deployment; revisit before
    horizontal scaling (see GatewayRateLimiter's own docstring for the
    Redis INCR + EXPIRE upgrade path).
    """

    _EXACT_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/sse-token"})
    _PREFIX_PATHS = ("/api/v1/executions", "/api/v1/missions", "/api/v1/sessions")

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        from modules.backend.core.config import get_app_config
        from modules.backend.gateway.security.rate_limiter import get_rate_limiter

        if not get_app_config().features.auth_rate_limit_enabled:
            return await call_next(request)

        if request.method != "POST":
            return await call_next(request)

        path = request.url.path
        if path not in self._EXACT_PATHS and not any(
            path.startswith(prefix) for prefix in self._PREFIX_PATHS
        ):
            return await call_next(request)

        client_key = _resolve_rate_limit_key(request)
        result = get_rate_limiter().check("api", client_key)
        if not result.allowed:
            logger.warning(
                "Request rate-limited",
                extra={"path": path, "retry_after_seconds": result.retry_after_seconds},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests — please retry shortly.",
                        "details": {"retry_after_seconds": result.retry_after_seconds},
                    },
                },
                headers={"Retry-After": str(result.retry_after_seconds)},
            )

        return await call_next(request)
