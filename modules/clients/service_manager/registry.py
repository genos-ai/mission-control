"""Registry of the managed dev services: temporal, api, worker, frontend.

One entry per service drives start, stop, status and the CLI's SERVICE
argument, so adding a service means adding one entry here and nothing in
services.py. Start functions are detached (daemon-style); the foreground
``start`` path keeps using ``DevRunner``.
"""

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from modules.clients.service_manager.constants import (
    DEFAULT_BIND_HOST,
    FRONTEND_PORT,
    PROJECT_ROOT,
    SERVICE_LOG_DIR,
    TEMPORAL_PORT,
    TEMPORAL_UI_PORT,
    TEMPORAL_WORKER_MODULE,
)
from modules.clients.service_manager.dev_runner import _backend_command
from modules.clients.service_manager.process_utils import (
    _connect_host_for_bind,
    _service_log_paths,
    _spawn_detached,
    _verify_daemon_ready,
    _wait_for_temporal,
    get_pids_by_cmdline,
    get_pids_on_port,
    stop_processes,
    temporal_db_args,
)


@dataclass(frozen=True)
class ServiceContext:
    """Per-invocation settings the services depend on."""

    port: int  # backend port
    host: str = DEFAULT_BIND_HOST


@dataclass(frozen=True)
class ManagedService:
    name: str  # the SERVICE token accepted on the command line
    label: Callable[[ServiceContext], str]
    find_pids: Callable[[ServiceContext], list[int]]
    start: Callable[[ServiceContext], None]


def _start_temporal(ctx: ServiceContext) -> None:
    log = SERVICE_LOG_DIR / "services-temporal.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")  # per-run log; a failure tail should show this start
    print("Starting Temporal server in background...")
    _spawn_detached(
        [
            "temporal",
            "server",
            "start-dev",
            "--port",
            str(TEMPORAL_PORT),
            "--ui-port",
            str(TEMPORAL_UI_PORT),
            *temporal_db_args(),
        ],
        PROJECT_ROOT,
        log,
    )
    if not _wait_for_temporal(log):
        sys.exit(1)
    print(f"  Temporal server: http://localhost:{TEMPORAL_UI_PORT}")


def _start_api(ctx: ServiceContext) -> None:
    log, _ = _service_log_paths(ctx.port)
    proc = _spawn_detached(_backend_command(ctx.host, ctx.port, reload=False), PROJECT_ROOT, log)
    _verify_daemon_ready(
        "Backend", proc, log, connect_host=_connect_host_for_bind(ctx.host), port=ctx.port
    )


def _start_worker(ctx: ServiceContext) -> None:
    log = SERVICE_LOG_DIR / "services-temporal-worker.log"
    _spawn_detached([sys.executable, "-m", TEMPORAL_WORKER_MODULE], PROJECT_ROOT, log)
    print("  Temporal Worker started")


def _start_frontend(ctx: ServiceContext) -> None:
    _, log = _service_log_paths(ctx.port)
    proc = _spawn_detached(["npm", "run", "dev"], PROJECT_ROOT / "modules" / "frontend", log)
    _verify_daemon_ready("Frontend", proc, log, connect_host="127.0.0.1", port=FRONTEND_PORT)


# Start order: each service depends on the ones before it. Stop runs in reverse.
SERVICES: tuple[ManagedService, ...] = (
    ManagedService(
        name="temporal",
        label=lambda ctx: f"Temporal (:{TEMPORAL_PORT})",
        find_pids=lambda ctx: get_pids_on_port(TEMPORAL_PORT),
        start=_start_temporal,
    ),
    ManagedService(
        name="api",
        label=lambda ctx: f"Backend (:{ctx.port})",
        find_pids=lambda ctx: get_pids_on_port(ctx.port),
        start=_start_api,
    ),
    ManagedService(
        name="worker",
        label=lambda ctx: "Temporal Worker",
        find_pids=lambda ctx: get_pids_by_cmdline(TEMPORAL_WORKER_MODULE),
        start=_start_worker,
    ),
    ManagedService(
        name="frontend",
        label=lambda ctx: f"Frontend (:{FRONTEND_PORT})",
        find_pids=lambda ctx: get_pids_on_port(FRONTEND_PORT),
        start=_start_frontend,
    ),
)

SERVICE_NAMES: tuple[str, ...] = tuple(s.name for s in SERVICES)


def resolve_services(
    names: Sequence[str] = (), *, include_frontend: bool = True
) -> list[ManagedService]:
    """Return the selected services in start order. No names selects all of them.

    Raises ValueError for an unknown name so callers decide how to report it.
    """
    unknown = sorted(set(names) - set(SERVICE_NAMES))
    if unknown:
        raise ValueError(f"unknown service(s): {', '.join(unknown)}")
    if names:
        return [s for s in SERVICES if s.name in names]
    return [s for s in SERVICES if include_frontend or s.name != "frontend"]


def start_services(services: Sequence[ManagedService], ctx: ServiceContext) -> None:
    """Start each service that is not already running, in the order given."""
    for service in services:
        pids = service.find_pids(ctx)
        if pids:
            print(f"  {service.label(ctx)} already running (PID {pids[0]})")
            continue
        service.start(ctx)


def stop_services(services: Sequence[ManagedService], ctx: ServiceContext) -> int:
    """Stop the services in reverse of the order given. Returns processes signalled."""
    return sum(
        stop_processes(partial(service.find_pids, ctx), service.label(ctx))
        for service in reversed(services)
    )
