#!/usr/bin/env python3
"""
Mission Control Service Manager

Manage all development services from one script.

Usage:
    python services.py start                  # Start everything (checks, migrate, seed, backend, frontend)  # noqa: E501
    python services.py start --daemon       # Start detached; logs in var/logs/services-*.log
    python services.py start --backend-only   # Backend only
    python services.py start --no-migrate     # Skip migrations
    python services.py stop                   # Stop backend + frontend
    python services.py stop --backend-only    # Stop everything except the frontend
    python services.py restart                # Stop then start
    python services.py restart api worker     # Restart only the API and the worker
    python services.py restart worker         # Restart only the Temporal worker
    python services.py stop frontend          # Stop one service
    python services.py restart --log-level WARNING --log-format console  # Errors/warnings only, colored  # noqa: E501
    python services.py status                 # Show what's running
    python services.py check                  # Preflight checks only

Docker/OrbStack is checked as part of preflight. If Docker is not running,
services.py will attempt to auto-start OrbStack (macOS) or Docker Desktop
before continuing. Docker is not a hard requirement — local-mode missions run
without it; only container-mode agent isolation (Plan 47) needs Docker.

PostgreSQL is a hard requirement. If it is not listening, preflight asks
whether to start the Homebrew launch agent (macOS) and clears a stale
postmaster.pid left by an unclean shutdown. It never starts without
confirmation; non-interactive runs just print the command to run.

Services are named api, worker, frontend and temporal. Naming one or more on start,
stop or restart acts on only those. Named services always run detached and skip
preflight, migrations and seeding. Stopping or restarting a named service is refused
when the stack runs in a foreground session, because that session shuts everything
down as soon as one service exits.

Daemon mode uses a new process session (no controlling terminal), stdin disconnected,
stdout/stderr appended to per-service log files, and a TCP readiness check before exit.
It cannot be combined with uvicorn --reload (multi-process supervisor).
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from modules.clients.service_manager.constants import (  # noqa: E402
    BACKEND_PORT,
    DEFAULT_BIND_HOST,
    FRONTEND_PORT,
    SERVICE_LOG_DIR,
    TEMPORAL_PORT,
    TEMPORAL_UI_PORT,
)
from modules.clients.service_manager.dev_runner import DevRunner  # noqa: E402
from modules.clients.service_manager.preflight import (  # noqa: E402
    dev_login_line,
    ensure_dev_user,
    preflight,
    run_migrations,
)
from modules.clients.service_manager.process_utils import (  # noqa: E402
    _wait_for_temporal,
    find_foreground_supervisor,
    get_pids_on_port,
)
from modules.clients.service_manager.registry import (  # noqa: E402
    SERVICE_NAMES,
    SERVICES,
    ManagedService,
    ServiceContext,
    resolve_services,
    start_services,
    stop_services,
)

# ===========================================================================
# Commands
# ===========================================================================


def _apply_logging_environment(args) -> None:
    """Pass the logging flags to child processes through their environment."""
    if getattr(args, "log_level", None):
        os.environ["MC_LOG_LEVEL"] = args.log_level
    if getattr(args, "log_format", None):
        os.environ["MC_LOG_FORMAT"] = args.log_format
    if getattr(args, "trace", False):
        os.environ["MC_AGENT_TRACE"] = "1"
        # Trace requires DEBUG level to capture log entries
        if not os.environ.get("MC_LOG_LEVEL"):
            os.environ["MC_LOG_LEVEL"] = "DEBUG"


def _prepare_services_environment(args) -> None:
    """Preflight, migrate, and seed. Exits the process on hard failure."""
    _apply_logging_environment(args)

    if not preflight(args.port, check_frontend=not args.backend_only):
        sys.exit(1)

    if not args.no_migrate:
        if not run_migrations():
            print("Migration failed. Fix the issue or use --no-migrate to skip.")
            sys.exit(1)
    else:
        print("\n  Migrations ........ skipped")

    if not args.no_seed:
        try:
            ensure_dev_user()
        except Exception as e:
            print(f"  Dev user seed ..... WARN ({e})")
    else:
        print("  Dev user .......... skipped")


def _context(args) -> ServiceContext:
    # stop and status have no --host; the bind host only matters when starting.
    return ServiceContext(port=args.port, host=getattr(args, "host", DEFAULT_BIND_HOST))


def _selected_services(args) -> list[ManagedService]:
    return resolve_services(args.services, include_frontend=not args.backend_only)


def _refuse_foreground_session(services: list[ManagedService], ctx: ServiceContext) -> None:
    """Exit if stopping these services would collapse a foreground session."""
    pids = [pid for service in services for pid in service.find_pids(ctx)]
    owner = find_foreground_supervisor(pids)
    if owner is not None:
        print(
            f"\n  Refusing: these services belong to a foreground session (PID {owner}), "
            "which shuts every service down when one exits.\n"
            "  Stop that session with Ctrl+C, or restart the whole stack: "
            "python services.py restart"
        )
        sys.exit(1)


def cmd_start_daemon(args):
    """Start services detached, with log files and readiness checks."""
    targeted = bool(args.services)
    print("=" * 50)
    print("  MISSION CONTROL — Start (daemon)")
    print("=" * 50)

    if targeted:
        _apply_logging_environment(args)
    else:
        _prepare_services_environment(args)

    print("\nStarting services in background...")
    start_services(_selected_services(args), _context(args))

    if targeted:
        return

    print("\n" + "-" * 50)
    print(f"  Backend API:    http://localhost:{args.port}")
    print(f"  Swagger UI:     http://localhost:{args.port}/docs")
    print(f"  Temporal UI:    http://localhost:{TEMPORAL_UI_PORT}")
    if not args.backend_only:
        print(f"  Frontend:       http://localhost:{FRONTEND_PORT}")
    print(dev_login_line())
    print("  Stop:           python services.py stop")
    print("-" * 50)
    print("Daemon processes are running; this terminal is free.\n")


def cmd_start(args):
    """Start development services."""
    if args.daemon or args.services:
        if args.services:
            print("Note: named services always run detached.\n")
        elif not args.no_reload:
            print(
                "Note: daemon mode always runs without uvicorn --reload "
                "(the reloader uses an extra supervisor process and is unsuitable for detached startup).\n"  # noqa: E501
            )
        cmd_start_daemon(args)
        return

    print("=" * 50)
    print("  MISSION CONTROL — Start")
    print("=" * 50)

    _prepare_services_environment(args)

    runner = DevRunner()
    signal.signal(signal.SIGINT, runner.shutdown)
    signal.signal(signal.SIGTERM, runner.shutdown)

    # Start Temporal server (unless already running)
    temporal_pids = get_pids_on_port(TEMPORAL_PORT)
    if not temporal_pids:
        print(f"\nStarting Temporal server at localhost:{TEMPORAL_PORT} ...")
        runner.start_temporal_server()
        if not _wait_for_temporal(SERVICE_LOG_DIR / "services-temporal.log"):
            runner.shutdown()
            sys.exit(1)
    else:
        print(f"\n  Temporal server already running (PID {temporal_pids[0]})")

    print(f"\nStarting backend at http://localhost:{args.port} ...")
    runner.start_backend(args.host, args.port, not args.no_reload)

    # Start Temporal worker (executes workflows)
    print("Starting Temporal worker ...")
    time.sleep(1)  # Give backend a head start for config loading
    runner.start_temporal_worker()

    if not args.backend_only:
        print(f"Starting frontend at http://localhost:{FRONTEND_PORT} ...")
        runner.start_frontend()

    print("\n" + "-" * 50)
    print(f"  Backend API:    http://localhost:{args.port}")
    print(f"  Swagger UI:     http://localhost:{args.port}/docs")
    print(f"  Temporal UI:    http://localhost:{TEMPORAL_UI_PORT}")
    if not args.backend_only:
        print(f"  Frontend:       http://localhost:{FRONTEND_PORT}")
    print(dev_login_line())
    print("-" * 50)
    print("Press Ctrl+C to stop all services\n")

    sys.exit(runner.wait())


def cmd_stop(args):
    """Stop running development services."""
    print("=" * 50)
    print("  MISSION CONTROL — Stop")
    print("=" * 50)

    services = _selected_services(args)
    ctx = _context(args)
    if args.services:
        _refuse_foreground_session(services, ctx)

    total = stop_services(services, ctx)

    if total == 0:
        print("\n  No services running.")
        return
    remaining = [pid for service in services for pid in service.find_pids(ctx)]
    if remaining:
        print(
            f"\n  Warning: {len(remaining)} process(es) still running. Try again or kill manually."  # noqa: E501
        )
    else:
        print(f"\n  Stopped {total} process(es).")


def cmd_restart(args):
    """Stop then start services."""
    cmd_stop(args)
    time.sleep(2)
    print()
    cmd_start(args)


def cmd_status(args):
    """Show which services are running."""
    print("=" * 50)
    print("  MISSION CONTROL — Status")
    print("=" * 50)
    print()

    ctx = _context(args)
    for service in SERVICES:
        pids = service.find_pids(ctx)
        state = f"RUNNING (PID {', '.join(str(p) for p in pids)})" if pids else "stopped"
        print(f"  {service.label(ctx)} ".ljust(21, ".") + f" {state}")

    redis_ok = False
    try:
        from redis import Redis

        r = Redis(host="localhost", port=6379, socket_connect_timeout=1)
        r.ping()
        r.close()
        redis_ok = True
    except Exception:
        redis_ok = False  # probe failed — service reported as stopped
    print(f"  Redis ............. {'RUNNING' if redis_ok else 'stopped'}")

    docker_label = "stopped"
    try:
        import docker as _docker

        _client = _docker.from_env()
        _client.ping()
        _info = _client.info()
        docker_label = f"RUNNING ({_info.get('ServerVersion', 'unknown')})"
    except Exception:
        pass  # probe failed — service reported as stopped
    print(f"  Docker ............ {docker_label}")

    pg_ok = False
    try:
        from modules.backend.core.config import get_app_config, get_settings

        db_cfg = get_app_config().database

        async def _pg():
            import asyncpg

            conn = await asyncpg.connect(
                host=db_cfg.host,
                port=db_cfg.port,
                user=db_cfg.user,
                password=get_settings().db_password,
                database=db_cfg.name,
                timeout=2,
            )
            await conn.close()

        asyncio.run(_pg())
        pg_ok = True
    except Exception:
        pg_ok = False  # probe failed — service reported as stopped
    print(f"  PostgreSQL ........ {'RUNNING' if pg_ok else 'stopped'}")
    print()


def cmd_check(args):
    """Run preflight checks only."""
    print("=" * 50)
    print("  MISSION CONTROL — Check")
    print("=" * 50)

    if preflight(args.port):
        print("\nAll checks passed.")
    else:
        sys.exit(1)


def _tree_arguments(sub: argparse.ArgumentParser) -> str:
    """Render a subparser's positionals then options, read from the parser itself."""
    positionals = [a for a in sub._actions if not a.option_strings and a.dest != "help"]
    options = [a for a in sub._actions if a.option_strings and a.dest != "help"]
    parts = [
        f"[{a.metavar or a.dest}{' ...' if a.nargs in ('*', '+') else ''}]" for a in positionals
    ] + [f"[{a.option_strings[-1]}]" for a in options]
    return (" " + " ".join(parts)) if parts else ""


def cmd_tree(args):
    """Show all services.py subcommands and their flags (rule 010.1)."""
    parser = _build_parser()
    subaction = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    help_by_name = {ca.dest: (ca.help or "") for ca in subaction._choices_actions}
    names = sorted(subaction.choices.keys())

    print("services  Mission Control service manager")
    for i, name in enumerate(names):
        last = i == len(names) - 1
        connector = "└── " if last else "├── "
        arguments = _tree_arguments(subaction.choices[name])
        print(f"{connector}{name}{arguments}  {help_by_name.get(name, '')}".rstrip())


# ===========================================================================
# CLI
# ===========================================================================


def _service_name(value: str) -> str:
    if value not in SERVICE_NAMES:
        raise argparse.ArgumentTypeError(
            f"invalid service '{value}' (choose from {', '.join(SERVICE_NAMES)})"
        )
    return value


def _add_services_argument(p: argparse.ArgumentParser, *, detached_note: bool) -> None:
    note = (
        " Named services run detached and skip preflight, migrations and seeding."
        if detached_note
        else ""
    )
    p.add_argument(
        "services",
        nargs="*",
        type=_service_name,
        metavar="SERVICE",
        help=f"Act on only these services ({', '.join(SERVICE_NAMES)}); default: all.{note}",
    )


def _add_start_arguments(p: argparse.ArgumentParser) -> None:
    _add_services_argument(p, detached_note=True)
    p.add_argument(
        "--host",
        default=DEFAULT_BIND_HOST,
        help=f"Backend host (default: {DEFAULT_BIND_HOST})",
    )
    p.add_argument(
        "--daemon",
        action="store_true",
        help=(
            "Run backend (and frontend) in the background: new session, logs appended to "
            f"var/logs/services-backend-<backend-port>.log and "
            f"var/logs/services-frontend-{FRONTEND_PORT}.log; "
            "exit after TCP readiness. Implies no uvicorn --reload."
        ),
    )
    p.add_argument("--no-reload", action="store_true", help="Disable backend auto-reload")
    p.add_argument(
        "--backend-only",
        action="store_true",
        help="Skip frontend dev server (cannot be combined with SERVICE)",
    )
    p.add_argument("--no-migrate", action="store_true", help="Skip database migrations")
    p.add_argument("--no-seed", action="store_true", help="Skip dev user seeding")
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Console log level filter (file logging unaffected)",
    )
    p.add_argument(
        "--log-format",
        choices=["json", "console"],
        default=None,
        help="Console log format: 'console' for colored human-readable output",
    )
    p.add_argument(
        "--trace",
        action="store_true",
        help="Enable agent tracing — logs full prompts/responses at DEBUG + emits to console",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mission Control service manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python services.py start                  Start all services
  python services.py start --daemon         Start detached (logs under var/logs/services-*.log)
  python services.py start --backend-only   Backend only (no frontend)
  python services.py start --no-migrate     Skip DB migrations
  python services.py stop                   Stop all services
  python services.py restart                Restart everything
  python services.py restart api worker     Restart only the API and the worker
  python services.py restart worker         Restart only the Temporal worker
  python services.py stop frontend          Stop one service
  python services.py status                 Show what's running
  python services.py check                  Run preflight checks
  python services.py tree                   Show all commands and flags

Logging:
  python services.py restart --log-level WARNING                  Errors/warnings only (no INFO)
  python services.py restart --log-level WARNING --log-format console  Colored + quiet
  python services.py restart --log-level DEBUG --log-format console   Full debug, colored
  python services.py restart --trace                              Trace agent prompts + responses (DEBUG + event bus)  # noqa: E501
        """,
    )

    # Shared options
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=BACKEND_PORT,
        help=f"Backend port (default: {BACKEND_PORT})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    scope_help = f"; name SERVICE... ({', '.join(SERVICE_NAMES)}) to limit it"
    p_start = subparsers.add_parser("start", help=f"Start development services{scope_help}")
    _add_start_arguments(p_start)

    p_stop = subparsers.add_parser("stop", help=f"Stop running services{scope_help}")
    _add_services_argument(p_stop, detached_note=False)
    p_stop.add_argument(
        "--backend-only",
        action="store_true",
        help="Leave the frontend running (cannot be combined with SERVICE)",
    )

    p_restart = subparsers.add_parser(
        "restart", help=f"Restart services (stop + start){scope_help}"
    )
    _add_start_arguments(p_restart)

    subparsers.add_parser("status", help="Show service status")
    subparsers.add_parser("check", help="Run preflight checks only")
    subparsers.add_parser("tree", help="Show all commands in a tree structure")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "check": cmd_check,
        "tree": cmd_tree,
    }

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if getattr(args, "services", None) and args.backend_only:
        parser.error("--backend-only cannot be combined with named services")

    commands[args.command](args)


if __name__ == "__main__":
    main()
