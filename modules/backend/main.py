"""
FastAPI Application Entry Point.

This is the main entry point for the Mission Control backend.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modules.backend.api import health
from modules.backend.api.v1 import router as api_v1_router
from modules.backend.core.config import get_app_config
from modules.backend.core.exception_handlers import register_exception_handlers
from modules.backend.core.logging import get_logger, setup_logging
from modules.backend.core.middleware import RequestContextMiddleware

logger = get_logger(__name__)

_app: FastAPI | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    app_config = get_app_config()
    setup_logging(level=app_config.logging.level)

    if app_config.features.security_startup_checks_enabled:
        from modules.backend.gateway.security.startup_checks import run_startup_checks
        run_startup_checks()

    logger.info(
        "Application starting",
        extra={
            "app_name": app_config.application.name,
            "env": app_config.application.environment,
        },
    )

    # Register Temporal schedule for autonomous plan dispatch.
    # Replaces MissionPlanDaemon — Temporal handles timing, dedup,
    # and worker coordination. Idempotent: silently skips if the
    # schedule already exists from a prior boot.
    try:
        from datetime import timedelta as _td

        from temporalio.client import (
            Schedule,
            ScheduleActionStartWorkflow,
            ScheduleIntervalSpec,
            ScheduleOverlapPolicy,
            SchedulePolicy,
            ScheduleSpec,
        )

        from modules.backend.temporal.client import get_temporal_client
        from modules.backend.temporal.scheduled_workflow import (
            ScheduledMissionCheckWorkflow,
        )

        temporal_client = await get_temporal_client()
        temporal_config = app_config.temporal
        schedule_id = "mission-plan-dispatch-schedule"

        try:
            await temporal_client.create_schedule(
                schedule_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        ScheduledMissionCheckWorkflow.run,
                        id="scheduled-mission-check",
                        task_queue=temporal_config.task_queue,
                    ),
                    spec=ScheduleSpec(
                        intervals=[ScheduleIntervalSpec(every=_td(seconds=5))],
                    ),
                    policy=SchedulePolicy(
                        overlap=ScheduleOverlapPolicy.SKIP,
                    ),
                ),
            )
            logger.info("Temporal dispatch schedule registered", extra={"schedule_id": schedule_id})
        except Exception as schedule_err:
            if "already registered" in str(schedule_err).lower() or "already exists" in str(schedule_err).lower():
                logger.info("Temporal dispatch schedule already exists")
            else:
                raise
    except Exception:  # noqa: BLE001
        logger.error("Failed to register Temporal dispatch schedule", exc_info=True)

    # Crash recovery: reconcile orphaned task states from prior crash.
    # Temporal's durable execution handles most cases, but tasks that
    # were mid-run when the BACKEND (not the worker) crashed still
    # need reconciliation.
    try:
        from redis.asyncio import Redis as AsyncRedis
        from modules.backend.core.config import get_redis_url
        from modules.backend.core.database import get_async_session
        from modules.backend.events.bus import SessionEventBus
        from modules.backend.services.mission_plan_crash_recovery import (
            reconcile_orphaned_task_states,
        )

        redis = AsyncRedis.from_url(get_redis_url())
        try:
            event_bus = SessionEventBus(redis)
            async with get_async_session() as db:
                stats = await reconcile_orphaned_task_states(db, event_bus)
                await db.commit()
            logger.info("Crash recovery completed", extra=stats)
        finally:
            await redis.close()
    except Exception:  # noqa: BLE001
        logger.error("Crash recovery failed — continuing startup", exc_info=True)

    yield

    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app_config = get_app_config()
    app_settings = app_config.application

    app = FastAPI(
        title=app_settings.name,
        description=app_settings.description,
        version=app_settings.version,
        docs_url="/docs" if app_settings.docs_enabled else None,
        redoc_url="/redoc" if app_settings.docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)

    cors_origins = app_settings.cors.origins
    if cors_origins:
        cors_security = app_config.security.cors
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=cors_security.allow_methods,
            allow_headers=cors_security.allow_headers,
        )

    register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(api_v1_router, prefix="/api/v1")

    _mount_channel_adapters(app, app_config)

    return app


def _mount_channel_adapters(app: FastAPI, app_config) -> None:
    """Mount enabled channel adapters via the gateway registry."""
    features = app_config.features

    if features.channel_telegram_enabled:
        try:
            from modules.clients.telegram.bot import get_bot, get_dispatcher
            from modules.clients.telegram.webhook import get_webhook_router
            from modules.backend.gateway.registry import get_adapter

            bot = get_bot()
            dp = get_dispatcher()
            app.include_router(get_webhook_router(bot, dp))

            adapter = get_adapter("telegram")
            if adapter:
                logger.info("Telegram channel mounted via gateway adapter")

        except (ImportError, RuntimeError, OSError) as e:
            logger.error(
                "Failed to mount Telegram channel",
                extra={"error": str(e)},
            )
            raise


def get_app() -> FastAPI:
    """
    Get the application instance (lazy initialization).

    This function creates the app on first call and caches it.
    Use this instead of importing `app` directly to avoid
    import-time configuration errors.
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


# For uvicorn: `uvicorn modules.backend.main:app`
def __getattr__(name: str) -> FastAPI:
    """Support lazy access to `app` for uvicorn compatibility."""
    if name == "app":
        return get_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
