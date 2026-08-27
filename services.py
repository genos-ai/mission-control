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
    python services.py stop --backend-only    # Stop backend only
    python services.py restart                # Stop then start
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
    FRONTEND_PORT,
    SERVICE_LOG_DIR,
    TEMPORAL_PORT,
    TEMPORAL_UI_PORT,
)
from modules.clients.service_manager.dev_runner import DevRunner, _backend_command  # noqa: E402
from modules.clients.service_manager.preflight import (  # noqa: E402
    ensure_dev_user,
    preflight,
    run_migrations,
)
from modules.clients.service_manager.process_utils import (  # noqa: E402
    _connect_host_for_bind,
    _service_log_paths,
    _spawn_detached,
    _verify_daemon_ready,
    _wait_for_temporal,
    get_pids_on_port,
    stop_port,
)

# ===========================================================================
# Commands
# ===========================================================================


def _prepare_services_environment(args) -> None:
    """Preflight, migrate, and seed. Exits the process on hard failure."""
    if getattr(args, "log_level", None):
        os.environ["MC_LOG_LEVEL"] = args.log_level
    if getattr(args, "log_format", None):
        os.environ["MC_LOG_FORMAT"] = args.log_format
    if getattr(args, "trace", False):
        os.environ["MC_AGENT_TRACE"] = "1"
        # Trace requires DEBUG level to capture log entries
        if not os.environ.get("MC_LOG_LEVEL"):
            os.environ["MC_LOG_LEVEL"] = "DEBUG"

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


def cmd_start_daemon(args):
    """Start backend (and optionally frontend) detached with log files and readiness checks."""
    print("=" * 50)
    print("  MISSION CONTROL — Start (daemon)")
    print("=" * 50)

    _prepare_services_environment(args)

    backend_log, frontend_log = _service_log_paths(args.port)
    connect_host = _connect_host_for_bind(args.host)

    # Start Temporal server if not already running
    temporal_pids = get_pids_on_port(TEMPORAL_PORT)
    if not temporal_pids:
        temporal_log = SERVICE_LOG_DIR / "services-temporal.log"
        temporal_log.parent.mkdir(parents=True, exist_ok=True)
        temporal_log.write_text("")  # per-run log; a failure tail should show this start
        print("\nStarting Temporal server in background...")
        _spawn_detached(
            [
                "temporal",
                "server",
                "start-dev",
                "--port",
                str(TEMPORAL_PORT),
                "--ui-port",
                str(TEMPORAL_UI_PORT),
            ],
            PROJECT_ROOT,
            temporal_log,
        )
        if not _wait_for_temporal(temporal_log):
            sys.exit(1)
        print(f"  Temporal server: http://localhost:{TEMPORAL_UI_PORT}")
    else:
        print(f"\n  Temporal server already running (PID {temporal_pids[0]})")

    print("\nStarting services in background...")
    proc_backend = _spawn_detached(
        _backend_command(args.host, args.port, reload=False),
        PROJECT_ROOT,
        backend_log,
    )
    _verify_daemon_ready(
        "Backend",
        proc_backend,
        backend_log,
        connect_host=connect_host,
        port=args.port,
    )

    # Start Temporal worker
    worker_log = SERVICE_LOG_DIR / "services-temporal-worker.log"
    _spawn_detached(
        [sys.executable, "-m", "modules.backend.temporal.worker"],
        PROJECT_ROOT,
        worker_log,
    )
    print("  Temporal Worker started")

    if not args.backend_only:
        frontend_dir = PROJECT_ROOT / "modules" / "frontend"
        proc_frontend = _spawn_detached(
            ["npm", "run", "dev"],
            frontend_dir,
            frontend_log,
        )
        _verify_daemon_ready(
            "Frontend",
            proc_frontend,
            frontend_log,
            connect_host="127.0.0.1",
            port=FRONTEND_PORT,
        )

    print("\n" + "-" * 50)
    print(f"  Backend API:    http://localhost:{args.port}")
    print(f"  Swagger UI:     http://localhost:{args.port}/docs")
    print(f"  Temporal UI:    http://localhost:{TEMPORAL_UI_PORT}")
    if not args.backend_only:
        print(f"  Frontend:       http://localhost:{FRONTEND_PORT}")
    print("  Login:          admin@missioncontrol.dev / admin")
    print("  Stop:           python services.py stop")
    print("-" * 50)
    print("Daemon processes are running; this terminal is free.\n")


def cmd_start(args):
    """Start development services."""
    if args.daemon:
        if not args.no_reload:
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
    print("  Login:          admin@missioncontrol.dev / admin")
    print("-" * 50)
    print("Press Ctrl+C to stop all services\n")

    sys.exit(runner.wait())


def cmd_stop(args):
    """Stop running development services."""
    print("=" * 50)
    print("  MISSION CONTROL — Stop")
    print("=" * 50)

    total = 0
    total += stop_port(args.port, f"Backend (:{args.port})")

    # Stop Temporal worker (find by process name)
    import psutil

    for proc in psutil.process_iter(["pid", "cmdline"], ad_value=None):
        cmdline = proc.info.get("cmdline") or []
        if any("modules.backend.temporal.worker" in str(c) for c in cmdline):
            proc.terminate()
            total += 1
            print(f"  Temporal Worker: sent SIGTERM to PID {proc.pid}")

    # Stop Temporal server
    total += stop_port(TEMPORAL_PORT, f"Temporal (:{TEMPORAL_PORT})")

    if not args.backend_only:
        total += stop_port(FRONTEND_PORT, f"Frontend (:{FRONTEND_PORT})")

    if total == 0:
        print("\n  No services running.")
    else:
        remaining = (
            get_pids_on_port(args.port)
            + get_pids_on_port(TEMPORAL_PORT)
            + ([] if args.backend_only else get_pids_on_port(FRONTEND_PORT))
        )
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

    backend_pids = get_pids_on_port(args.port)
    if backend_pids:
        print(
            f"\n  Backend (:{args.port})  .... RUNNING (PID {', '.join(str(p) for p in backend_pids)})"  # noqa: E501
        )
    else:
        print(f"\n  Backend (:{args.port})  .... stopped")

    temporal_pids = get_pids_on_port(TEMPORAL_PORT)
    if temporal_pids:
        print(
            f"  Temporal (:{TEMPORAL_PORT})  ... RUNNING (PID {', '.join(str(p) for p in temporal_pids)})"  # noqa: E501
        )
    else:
        print(f"  Temporal (:{TEMPORAL_PORT})  ... stopped")

    # Check Temporal worker by process name
    import psutil

    worker_running = False
    for proc in psutil.process_iter(["pid", "cmdline"], ad_value=None):
        cmdline = proc.info.get("cmdline") or []
        if any("modules.backend.temporal.worker" in str(c) for c in cmdline):
            print(f"  Temporal Worker .. RUNNING (PID {proc.pid})")
            worker_running = True
            break
    if not worker_running:
        print("  Temporal Worker .. stopped")

    frontend_pids = get_pids_on_port(FRONTEND_PORT)
    if frontend_pids:
        print(
            f"  Frontend (:{FRONTEND_PORT}) ... RUNNING (PID {', '.join(str(p) for p in frontend_pids)})"  # noqa: E501
        )
    else:
        print(f"  Frontend (:{FRONTEND_PORT}) ... stopped")

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
        sub = subaction.choices[name]
        flags = [
            a.option_strings[-1] for a in sub._actions if a.option_strings and a.dest != "help"
        ]
        flag_str = (" " + " ".join(f"[{f}]" for f in flags)) if flags else ""
        print(f"{connector}{name}{flag_str}  {help_by_name.get(name, '')}".rstrip())


# ===========================================================================
# CLI
# ===========================================================================


def _add_start_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default="0.0.0.0", help="Backend host (default: 0.0.0.0)")
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
    p.add_argument("--backend-only", action="store_true", help="Skip frontend dev server")
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

    p_start = subparsers.add_parser("start", help="Start development services")
    _add_start_arguments(p_start)

    p_stop = subparsers.add_parser("stop", help="Stop running services")
    p_stop.add_argument("--backend-only", action="store_true", help="Stop backend only")

    p_restart = subparsers.add_parser("restart", help="Restart services (stop + start)")
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

    commands[args.command](args)


if __name__ == "__main__":
    main()
