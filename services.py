#!/usr/bin/env python3
"""
Mission Control Service Manager

Manage all development services from one script.

Usage:
    python services.py start                  # Start everything (checks, migrate, seed, backend, frontend)
    python services.py start --daemon       # Start detached; logs in var/logs/services-*.log
    python services.py start --backend-only   # Backend only
    python services.py start --no-migrate     # Skip migrations
    python services.py stop                   # Stop backend + frontend
    python services.py stop --backend-only    # Stop backend only
    python services.py restart                # Stop then start
    python services.py status                 # Show what's running
    python services.py check                  # Preflight checks only

Docker/OrbStack is checked as part of preflight. If Docker is not running,
services.py will attempt to auto-start OrbStack (macOS) or Docker Desktop
before continuing. Docker is not a hard requirement — local-mode missions run
without it; only container-mode agent isolation (Plan 47) needs Docker.

Daemon mode uses a new process session (no controlling terminal), stdin disconnected,
stdout/stderr appended to per-service log files, and a TCP readiness check before exit.
It cannot be combined with uvicorn --reload (multi-process supervisor).
"""

import argparse
import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

BACKEND_PORT = 8100
FRONTEND_PORT = 5174

# Log directory aligns with application logging (var/logs).
SERVICE_LOG_DIR = PROJECT_ROOT / "var" / "logs"
DAEMON_START_TIMEOUT_SEC = 90.0
DAEMON_LOG_TAIL_BYTES = 8000


# ---------------------------------------------------------------------------
# Port utilities
# ---------------------------------------------------------------------------

def get_pids_on_port(port: int) -> list[int]:
    """Return PIDs listening on a port."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-t"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [int(p) for p in result.stdout.strip().split("\n") if p.isdigit()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def kill_pids(pids: list[int], label: str) -> int:
    """Terminate a list of PIDs gracefully, force-kill after timeout."""
    if not pids:
        return 0

    killed = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  Permission denied killing PID {pid}")

    if killed:
        print(f"  {label}: sent SIGTERM to {killed} process(es) (PID {', '.join(str(p) for p in pids)})")

        # Wait for processes to die, force-kill survivors
        deadline = time.time() + 5
        while time.time() < deadline:
            alive = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except ProcessLookupError:
                    pass
            if not alive:
                break
            time.sleep(0.5)
        else:
            for pid in alive:
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"  Force-killed PID {pid}")
                except (ProcessLookupError, PermissionError):
                    pass

    return killed


def stop_port(port: int, label: str) -> int:
    """Kill all processes on a port, retrying to catch respawned children."""
    total = 0
    for _ in range(3):
        pids = get_pids_on_port(port)
        if not pids:
            break
        total += kill_pids(pids, label)
        time.sleep(1)
    return total


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_redis() -> bool:
    """Check Redis connectivity."""
    try:
        from redis import Redis
        r = Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        r.close()
        print("  Redis ............. OK")
        return True
    except Exception as e:
        print(f"  Redis ............. FAIL ({e})")
        print("    Start Redis: brew services start redis  OR  redis-server --daemonize yes")
        return False


def check_docker(*, try_start: bool = False) -> bool:
    """Check Docker daemon connectivity. Optionally starts OrbStack on macOS.

    When ``try_start=True`` and Docker is not reachable, the function tries:
      1. ``orbctl start`` if orbctl is on PATH — blocks until OrbStack is ready.
      2. ``open -a OrbStack`` if the app exists — then polls up to 90s.
      3. ``open -a Docker`` for Docker Desktop — then polls up to 90s.

    Returns True when Docker is reachable.
    """
    def _docker_alive() -> bool:
        try:
            import docker
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False

    if _docker_alive():
        print("  Docker ............ OK")
        return True

    if not try_start:
        print("  Docker ............ FAIL (daemon not reachable)")
        print("    Start Docker: open -a OrbStack  OR  open -a Docker")
        return False

    # Determine what's available
    orbctl_path = subprocess.run(["which", "orbctl"], capture_output=True, text=True)
    has_orbctl = orbctl_path.returncode == 0
    orbstack_app = Path("/Applications/OrbStack.app")
    docker_app = Path("/Applications/Docker.app")

    if has_orbctl:
        # orbctl start blocks until OrbStack is fully ready (Docker socket up).
        print("  Docker ............ starting OrbStack (orbctl start)...", flush=True)
        result = subprocess.run(
            ["orbctl", "start"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and _docker_alive():
            print("  Docker ............ OK (OrbStack ready)")
            return True
        # orbctl reported success but socket still not up — fall through to poll
    elif orbstack_app.exists():
        print("  Docker ............ starting OrbStack...", flush=True)
        subprocess.run(["open", "-a", "OrbStack"], check=False)
    elif docker_app.exists():
        print("  Docker ............ starting Docker Desktop...", flush=True)
        subprocess.run(["open", "-a", "Docker"], check=False)
    else:
        print("  Docker ............ FAIL (daemon not reachable, no launcher found)")
        print("    Install OrbStack: https://orbstack.dev  OR  Docker Desktop")
        return False

    # Poll — OrbStack typically takes 15-60s from cold start; allow 90s.
    timeout_sec = 90
    deadline = time.time() + timeout_sec
    print(f"  Docker ............ waiting for daemon (up to {timeout_sec}s)", end="", flush=True)
    while time.time() < deadline:
        if _docker_alive():
            print(" OK")
            return True
        print(".", end="", flush=True)
        time.sleep(2)

    print(f" FAIL")
    print(f"  Docker ............ FAIL (did not start within {timeout_sec}s)")
    return False


def check_postgres() -> bool:
    """Check PostgreSQL connectivity using config from database.yaml."""
    try:
        from modules.backend.core.config import get_app_config, get_settings
        db_cfg = get_app_config().database
        db_password = get_settings().db_password

        async def _check():
            import asyncpg
            conn = await asyncpg.connect(
                host=db_cfg.host,
                port=db_cfg.port,
                user=db_cfg.user,
                password=db_password,
                database=db_cfg.name,
                timeout=3,
            )
            await conn.close()

        asyncio.run(_check())
        print(f"  PostgreSQL ........ OK ({db_cfg.host}:{db_cfg.port}/{db_cfg.name})")
        return True
    except Exception as e:
        print(f"  PostgreSQL ........ FAIL ({e})")
        return False


def check_port_free(port: int) -> bool:
    """Check if a port is free."""
    pids = get_pids_on_port(port)
    if pids:
        print(f"  Port {port} ........... IN USE (PID {', '.join(str(p) for p in pids)})")
        return False
    print(f"  Port {port} ........... free")
    return True


def preflight(backend_port: int, check_frontend: bool = True) -> bool:
    """Run all preflight checks. Returns True if all pass."""
    print("\nPreflight checks...")
    redis_ok = check_redis()
    pg_ok = check_postgres()
    docker_ok = check_docker(try_start=True)
    port_ok = check_port_free(backend_port)
    if check_frontend:
        check_port_free(FRONTEND_PORT)

    if not (redis_ok and pg_ok):
        print("\nRequired services are not running. Fix the issues above and retry.")
        return False
    if not port_ok:
        print(f"\nPort {backend_port} is in use. Run 'python services.py stop' first or use --port <other>.")
        return False
    if not docker_ok:
        print("\nWarning: Docker is not available. Container-mode agent execution will not work.")
        print("  Continuing without Docker (local-mode missions will still run).")
    return True


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def run_migrations() -> bool:
    """Run alembic upgrade head."""
    print("\nRunning migrations...")
    result = subprocess.run(
        [sys.executable, "admin.py", "migrate", "upgrade", "head"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if result.returncode == 0:
        print("  Migrations ........ OK")
        return True
    else:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"  Migrations ........ FAIL\n    {stderr[:200]}")
        return False


# ---------------------------------------------------------------------------
# Seed dev user
# ---------------------------------------------------------------------------

def ensure_dev_user() -> None:
    """Create a default admin user if none exists."""
    print("\nChecking dev user...")

    async def _ensure():
        from modules.backend.core.database import get_session_factory
        from modules.backend.core.security import hash_password
        from sqlalchemy import text

        session_factory = get_session_factory()

        async with session_factory() as session:
            row = (await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": "admin@missioncontrol.dev"},
            )).first()

            if row:
                print("  admin@missioncontrol.dev .... exists")
                return

            import uuid
            from datetime import datetime

            pw_hash = hash_password("admin")
            user_id = str(uuid.uuid4())
            now = datetime.utcnow()
            await session.execute(
                text("""
                    INSERT INTO users (id, email, display_name, hashed_password,
                                       system_role, is_active, is_service_account,
                                       created_at, updated_at)
                    VALUES (:id, :email, :name, :pw, :role, true, false, :now, :now)
                """),
                {
                    "id": user_id,
                    "email": "admin@missioncontrol.dev",
                    "name": "Admin",
                    "pw": pw_hash,
                    "role": "admin",
                    "now": now,
                },
            )
            await session.commit()
            print("  admin@missioncontrol.dev .... CREATED (password: admin)")

    asyncio.run(_ensure())


# ---------------------------------------------------------------------------
# Detached (daemon) process support
# ---------------------------------------------------------------------------


def _connect_host_for_bind(bind_host: str) -> str:
    """Host to use for local TCP checks when the server binds to bind_host."""
    if bind_host in ("0.0.0.0", "", "::", "[::]"):
        return "127.0.0.1"
    return bind_host


def _service_log_paths(backend_port: int) -> tuple[Path, Path]:
    """Fixed log paths for daemon mode (no PID file required)."""
    backend_log = SERVICE_LOG_DIR / f"services-backend-{backend_port}.log"
    frontend_log = SERVICE_LOG_DIR / f"services-frontend-{FRONTEND_PORT}.log"
    return backend_log, frontend_log


def _read_log_tail(path: Path, max_bytes: int = DAEMON_LOG_TAIL_BYTES) -> str:
    if not path.is_file():
        return f"(no log file at {path})"
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def _wait_for_tcp(host: str, port: int, *, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _spawn_detached(
    cmd: list[str],
    cwd: Path,
    log_path: Path,
) -> subprocess.Popen:
    """Start a child in a new session with stdin closed and logs appended.

    The parent's handle to the log file is closed after spawn so only the
    child retains the descriptor; output is line-buffered UTF-8.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(
        log_path,
        "a",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )
    try:
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_f.close()


def _verify_daemon_ready(
    label: str,
    proc: subprocess.Popen,
    log_path: Path,
    *,
    connect_host: str,
    port: int,
) -> None:
    """Ensure the process did not exit immediately and the port accepts TCP."""
    time.sleep(0.35)
    code = proc.poll()
    if code is not None:
        print(f"  {label} .......... FAIL (exited early with code {code})")
        print(_read_log_tail(log_path))
        sys.exit(1)

    if not _wait_for_tcp(connect_host, port, timeout_sec=DAEMON_START_TIMEOUT_SEC):
        code = proc.poll()
        print(f"  {label} .......... FAIL (port {port} not accepting connections in time)")
        if code is not None:
            print(f"  Process exited with code {code}.")
        print(_read_log_tail(log_path))
        sys.exit(1)

    print(f"  {label} .......... OK (PID {proc.pid}, log {log_path})")


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

class DevRunner:
    """Manages backend and frontend subprocesses."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []
        self._shutting_down = False

    def start_backend(self, host: str, port: int, reload: bool) -> subprocess.Popen:
        proc = subprocess.Popen(
            _backend_command(host, port, reload=reload),
            cwd=PROJECT_ROOT,
        )
        self.procs.append(proc)
        return proc

    def start_frontend(self) -> subprocess.Popen:
        frontend_dir = PROJECT_ROOT / "modules" / "frontend"
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
        )
        self.procs.append(proc)
        return proc

    def shutdown(self, signum=None, frame=None):
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\n\nShutting down...")

        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()

        deadline = time.time() + 5
        for proc in self.procs:
            remaining = max(0.1, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        print("All services stopped.")

    def wait(self):
        """Block until any child exits or Ctrl-C."""
        try:
            while True:
                for proc in self.procs:
                    ret = proc.poll()
                    if ret is not None:
                        name = " ".join(proc.args[:4]) if isinstance(proc.args, list) else str(proc.args)
                        print(f"\nProcess exited (code {ret}): {name}")
                        self.shutdown()
                        return ret
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.shutdown()
            return 0


# ===========================================================================
# Commands
# ===========================================================================


def _prepare_services_environment(args) -> None:
    """Preflight, migrate, and seed. Exits the process on hard failure."""
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


def _backend_command(host: str, port: int, *, reload: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "modules.backend.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")
    return cmd


def cmd_start_daemon(args):
    """Start backend (and optionally frontend) detached with log files and readiness checks."""
    print("=" * 50)
    print("  MISSION CONTROL — Start (daemon)")
    print("=" * 50)

    _prepare_services_environment(args)

    backend_log, frontend_log = _service_log_paths(args.port)
    connect_host = _connect_host_for_bind(args.host)

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
    print(f"  Backend API:  http://localhost:{args.port}")
    print(f"  Swagger UI:   http://localhost:{args.port}/docs")
    if not args.backend_only:
        print(f"  Frontend:     http://localhost:{FRONTEND_PORT}")
    print(f"  Login:        admin@missioncontrol.dev / admin")
    print("  Stop:         python services.py stop")
    print("-" * 50)
    print("Daemon processes are running; this terminal is free.\n")


def cmd_start(args):
    """Start development services."""
    if args.daemon:
        if not args.no_reload:
            print(
                "Note: daemon mode always runs without uvicorn --reload "
                "(the reloader uses an extra supervisor process and is unsuitable for detached startup).\n"
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

    print(f"\nStarting backend at http://localhost:{args.port} ...")
    runner.start_backend(args.host, args.port, not args.no_reload)

    if not args.backend_only:
        print(f"Starting frontend at http://localhost:{FRONTEND_PORT} ...")
        runner.start_frontend()

    print("\n" + "-" * 50)
    print(f"  Backend API:  http://localhost:{args.port}")
    print(f"  Swagger UI:   http://localhost:{args.port}/docs")
    if not args.backend_only:
        print(f"  Frontend:     http://localhost:{FRONTEND_PORT}")
    print(f"  Login:        admin@missioncontrol.dev / admin")
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

    if not args.backend_only:
        total += stop_port(FRONTEND_PORT, f"Frontend (:{FRONTEND_PORT})")

    if total == 0:
        print("\n  No services running.")
    else:
        # Final verification
        remaining = get_pids_on_port(args.port) + ([] if args.backend_only else get_pids_on_port(FRONTEND_PORT))
        if remaining:
            print(f"\n  Warning: {len(remaining)} process(es) still running. Try again or kill manually.")
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
        print(f"\n  Backend (:{args.port})  .... RUNNING (PID {', '.join(str(p) for p in backend_pids)})")
    else:
        print(f"\n  Backend (:{args.port})  .... stopped")

    frontend_pids = get_pids_on_port(FRONTEND_PORT)
    if frontend_pids:
        print(f"  Frontend (:{FRONTEND_PORT}) ... RUNNING (PID {', '.join(str(p) for p in frontend_pids)})")
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
        pass
    print(f"  Redis ............. {'RUNNING' if redis_ok else 'stopped'}")

    docker_ok = False
    docker_label = "stopped"
    try:
        import docker as _docker
        _client = _docker.from_env()
        _client.ping()
        docker_ok = True
        _info = _client.info()
        docker_label = f"RUNNING ({_info.get('ServerVersion', 'unknown')})"
    except Exception:
        pass
    print(f"  Docker ............ {docker_label}")

    pg_ok = False
    try:
        from modules.backend.core.config import get_app_config, get_settings
        db_cfg = get_app_config().database

        async def _pg():
            import asyncpg
            conn = await asyncpg.connect(
                host=db_cfg.host, port=db_cfg.port,
                user=db_cfg.user, password=get_settings().db_password,
                database=db_cfg.name, timeout=2,
            )
            await conn.close()

        asyncio.run(_pg())
        pg_ok = True
    except Exception:
        pass
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


# ===========================================================================
# CLI
# ===========================================================================

def main():
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
        """,
    )

    # Shared options
    parser.add_argument("--port", "-p", type=int, default=BACKEND_PORT, help=f"Backend port (default: {BACKEND_PORT})")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    def add_start_arguments(p: argparse.ArgumentParser) -> None:
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

    # -- start --
    p_start = subparsers.add_parser("start", help="Start development services")
    add_start_arguments(p_start)

    # -- stop --
    p_stop = subparsers.add_parser("stop", help="Stop running services")
    p_stop.add_argument("--backend-only", action="store_true", help="Stop backend only")

    # -- restart --
    p_restart = subparsers.add_parser("restart", help="Restart services (stop + start)")
    add_start_arguments(p_restart)

    # -- status --
    subparsers.add_parser("status", help="Show service status")

    # -- check --
    subparsers.add_parser("check", help="Run preflight checks only")

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "check": cmd_check,
    }

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands[args.command](args)


if __name__ == "__main__":
    main()
