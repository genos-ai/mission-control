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
import os
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


_mission_events_enabled = False
_event_queue: asyncio.Queue | None = None
_drain_task: asyncio.Task | None = None


def mission_event_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that bridges WARNING+ logs to the mission event stream.

    If the event_dict contains ``mission_id`` and the log level is WARNING
    or above, enqueues a ``(mission_id, message, level, source)`` tuple
    for the background drain task to publish. The processor itself does
    zero async work — it just pushes to an in-memory queue.

    A single long-lived ``_drain_mission_event_queue`` task reads from
    the queue and publishes to Redis using one persistent connection.

    Enabled by ``setup_logging(enable_mission_events=True)`` — default for
    the backend server and Temporal worker; off for CLI/TUI.
    """
    if not _mission_events_enabled or _event_queue is None:
        return event_dict

    mission_id = event_dict.get("mission_id")
    if not mission_id:
        extra = event_dict.get("extra")
        if isinstance(extra, dict):
            mission_id = extra.get("mission_id")
    if not mission_id:
        return event_dict

    level = event_dict.get("level", method_name)
    if level not in ("warning", "error", "critical"):
        return event_dict

    message = event_dict.get("event", "")
    source = event_dict.get("source") or event_dict.get("logger", "logger")

    try:
        _event_queue.put_nowait((str(mission_id), str(message), level, str(source)))
    except asyncio.QueueFull:
        pass  # Drop under backpressure — logging must never block

    return event_dict


async def _drain_mission_event_queue(queue: asyncio.Queue) -> None:
    """Background task: drain the event queue and publish to Redis.

    Uses a single persistent Redis connection. Reconnects on failure.
    Runs for the lifetime of the process.
    """
    import uuid as _uuid

    from redis.asyncio import Redis as AsyncRedis
    from modules.backend.core.config import get_redis_url
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.events.types import SystemEvent

    redis = None

    while True:
        mission_id, message, level, source = await queue.get()
        try:
            if redis is None:
                redis = AsyncRedis.from_url(get_redis_url())

            bus = SessionEventBus(redis, mission_id=mission_id)
            await bus.publish_to_mission(
                mission_id,
                SystemEvent(
                    session_id=_uuid.uuid4(),
                    source=source,
                    level=level,
                    message=message,
                    mission_id=mission_id,
                ),
            )
        except Exception as drain_exc:
            # Connection lost — reset so next iteration reconnects.
            # Use stdlib logger (not structlog) to avoid re-entrant
            # processor calls that would loop back into this queue.
            logging.getLogger("mission_event_drain").debug(
                "Mission event drain error: %s", drain_exc, exc_info=True,
            )
            try:
                if redis is not None:
                    await redis.aclose()
            except Exception:
                pass
            redis = None
        finally:
            queue.task_done()


def start_mission_event_drain() -> None:
    """Start the background drain task. Call once from an async context.

    Safe to call multiple times — only starts one drain task.
    """
    global _event_queue, _drain_task
    if _drain_task is not None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # No event loop — skip

    _event_queue = asyncio.Queue(maxsize=1000)
    _drain_task = loop.create_task(_drain_mission_event_queue(_event_queue))


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

    # Environment overrides for console handler only (set by services.py CLI flags).
    # These do NOT affect file logging — file handler always uses config level/format.
    console_level_override = os.environ.get("MC_LOG_LEVEL")
    console_format_override = os.environ.get("MC_LOG_FORMAT")

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
            mission_event_processor,
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
        if console_format_override and console_format_override.lower() == "console":
            console_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=True),
                foreign_pre_chain=shared_processors,
            ))
        else:
            console_handler.setFormatter(console_formatter)
        if console_level_override:
            console_handler.setLevel(getattr(logging, console_level_override.upper(), log_level))
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

    global _mission_events_enabled
    _mission_events_enabled = enable_mission_events

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
