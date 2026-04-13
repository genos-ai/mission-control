"""
Centralized Logging Configuration.

All modules must use this logging setup. Do not create standalone loggers.
Configuration is loaded from config/settings/logging.yaml.

Structured fields in every JSON log record:
    timestamp   - ISO 8601 UTC timestamp
    level       - Log level (debug, info, warning, error, critical)
    logger      - Module path (e.g., modules.backend.core.middleware)
    event       - Log message
    func_name   - Function that emitted the log
    lineno      - Line number in source file
    source      - Origin context, set explicitly (web, cli, tui, telegram, etc.)
    request_id  - Request correlation ID (when in HTTP request context)

Additional fields are passed via extra kwargs or structlog context binding.

Usage:
    from modules.backend.core.logging import get_logger, setup_logging

    # Setup at application start (loads from logging.yaml)
    setup_logging()

    # Override config values if needed
    setup_logging(level="DEBUG", format_type="console")

    # Get logger in modules
    logger = get_logger(__name__)
    logger.info("Message", extra={"key": "value"})

    # Explicit source for non-HTTP contexts
    from modules.backend.core.logging import log_with_source
    log_with_source(logger, "telegram", "info", "Update received", chat_id=123)

Log File:
    var/logs/system.jsonl — JSONL, rotates at interval from logging.yaml (default: local midnight);
    dated backups (e.g. system.jsonl.2026-04-07). Filter by 'source' field.
"""

import asyncio
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import Processor

from modules.backend.core.config import find_project_root, load_yaml_config

VALID_SOURCES = frozenset({
    "web",
    "cli",
    "tui",
    "mobile",
    "telegram",
    "api",
    "tasks",
    "internal",
    "events",
})
"""
Recognized log source values — for documentation and validation.
Source is always set explicitly by the caller. Never guessed from logger names.
"""

_logging_config: dict[str, Any] | None = None


def _load_logging_config() -> dict[str, Any]:
    """
    Load logging configuration from config/settings/logging.yaml.

    Returns:
        Dictionary containing logging configuration

    Raises:
        FileNotFoundError: If logging.yaml does not exist
    """
    global _logging_config
    if _logging_config is None:
        _logging_config = load_yaml_config("logging.yaml")
    return _logging_config


def _get_logging_config() -> dict[str, Any]:
    """
    Get the cached logging configuration.

    Returns:
        Dictionary containing logging configuration
    """
    return _load_logging_config()


def _resolve_log_path(configured_path: str) -> Path:
    """
    Resolve the log file path relative to project root.

    Args:
        configured_path: Path from logging.yaml (relative to project root)

    Returns:
        Absolute Path to the log file
    """
    project_root = find_project_root()
    return project_root / configured_path


class MissionEventHandler(logging.Handler):
    """Bridges the logger to the mission event stream.

    Any log record at WARNING or above that carries ``mission_id`` in its
    ``extra`` dict is automatically published as a ``SystemEvent`` to the
    mission's Redis Pub/Sub channel. This makes errors visible in the
    console, narrative, and SSE streams without requiring manual
    ``event_bus.publish()`` calls at every error site.

    The handler is async-safe: it schedules a fire-and-forget coroutine
    on the running event loop. If no loop is running (CLI, tests), the
    record is silently skipped — the file/console handlers still capture it.

    Registered by ``setup_logging()`` when ``enable_mission_events`` is True
    (default for the backend; off for CLI/TUI which have no Redis).
    """

    def emit(self, record: logging.LogRecord) -> None:
        # structlog stores extra fields directly on the record
        mission_id = getattr(record, "mission_id", None)
        if not mission_id:
            # Also check the extra dict (standard logging pattern)
            extra = getattr(record, "_extra", None) or {}
            mission_id = extra.get("mission_id")
        if not mission_id:
            return

        level = record.levelname.lower()
        if level not in ("warning", "error", "critical"):
            return

        message = record.getMessage()
        source = getattr(record, "source", None) or record.name

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No event loop — CLI/test context, skip silently

        loop.create_task(
            _publish_mission_event(str(mission_id), message, level=level, source=source)
        )


async def _publish_mission_event(
    mission_id: str,
    message: str,
    *,
    level: str = "error",
    source: str = "logger",
) -> None:
    """Fire-and-forget: publish a SystemEvent to the mission's stream."""
    try:
        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url
        from modules.backend.events.bus import SessionEventBus
        from modules.backend.events.types import SystemEvent

        redis = AsyncRedis.from_url(get_redis_url())
        try:
            bus = SessionEventBus(redis, mission_id=mission_id)
            await bus.publish_to_mission(
                mission_id,
                SystemEvent(
                    session_id="",
                    source=source,
                    level=level,
                    message=message,
                    mission_id=mission_id,
                ),
            )
        finally:
            await redis.aclose()
    except Exception:
        # Never let event emission break the application
        pass


def setup_logging(
    level: str | None = None,
    format_type: str | None = None,
    enable_console: bool | None = None,
    enable_file_logging: bool | None = None,
    enable_mission_events: bool = False,
) -> None:
    """
    Configure structured logging for the application.

    Configuration is loaded from config/settings/logging.yaml.
    Parameters passed to this function override the YAML configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Overrides config.
        format_type: Output format ('json' or 'console'). Overrides config.
        enable_console: Whether to enable console output. Overrides config.
        enable_file_logging: Whether to write to JSONL file. Overrides config.
        enable_mission_events: Whether to bridge WARNING+ logs with mission_id
            to the mission event stream via Redis. True for backend server,
            False for CLI/TUI (no Redis available).
    """
    config = _get_logging_config()

    effective_level = level if level is not None else config["level"]
    effective_format = format_type if format_type is not None else config["format"]

    handlers_config = config["handlers"]
    console_config = handlers_config["console"]
    file_config = handlers_config["file"]

    effective_console_enabled = (
        enable_console if enable_console is not None
        else console_config["enabled"]
    )
    effective_file_enabled = (
        enable_file_logging if enable_file_logging is not None
        else file_config["enabled"]
    )

    log_level = getattr(logging, effective_level.upper())

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ],
        ),
    ]

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if effective_format == "console":
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=shared_processors,
        )
    else:
        console_formatter = json_formatter

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if effective_console_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    if effective_file_enabled:
        log_path = _resolve_log_path(file_config["path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = TimedRotatingFileHandler(
            filename=str(log_path),
            when=file_config["rotation_when"],
            interval=file_config["rotation_interval"],
            backupCount=file_config["backup_count"],
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)

    if enable_mission_events:
        mission_handler = MissionEventHandler()
        mission_handler.setLevel(logging.WARNING)
        root_logger.addHandler(mission_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> Any:
    """
    Get a logger instance for the given name.

    Args:
        name: Logger name, typically __name__

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def log_with_source(logger: Any, source: str, level: str, message: str, **kwargs: Any) -> None:
    """
    Log a message with an explicit source.

    Use this when you need to set the source outside of HTTP request context
    (e.g., in Telegram handlers, background tasks, CLI commands).

    Args:
        logger: The logger instance
        source: Log source (web, cli, tui, telegram, api, tasks, internal)
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        **kwargs: Additional context fields

    Raises:
        AttributeError: If level is not a valid log level

    Example:
        log_with_source(logger, "tasks", "info", "Task completed", task_id="abc")
    """
    log_method = getattr(logger, level.lower())
    log_method(message, source=source, **kwargs)


def bind_context(**kwargs: Any) -> None:
    """Bind key-value pairs to the structlog context for the current task.

    Wraps structlog.contextvars.bind_contextvars() so entry scripts
    do not need to import structlog directly.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all structlog context variables."""
    structlog.contextvars.clear_contextvars()
