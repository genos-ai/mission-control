"""Preflight checks: Redis, Docker, PostgreSQL, ports, migrations, dev user.

Split out of root services.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from modules.clients.service_manager.constants import FRONTEND_PORT, PROJECT_ROOT
from modules.clients.service_manager.process_utils import _wait_for_tcp, get_pids_on_port


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
    """Check Docker daemon connectivity. Optionally auto-starts a runtime on macOS.

    On macOS with ``try_start=True``:
      - Tries ``orbctl start`` (blocks until ready) if orbctl is on PATH.
      - Otherwise launches OrbStack.app or Docker.app and polls up to 30s.
    On Linux: reports failure only — systemd or the user manages the daemon.

    Returns True when Docker is reachable.
    """

    def _docker_alive() -> tuple[bool, str]:
        """Run ``docker info`` and return (ok, error_message)."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout or "docker info failed").strip()
        except FileNotFoundError:
            return False, "docker CLI not found on PATH"
        except subprocess.TimeoutExpired:
            return False, "daemon not responding (timed out after 5s)"

    ok, err = _docker_alive()
    if ok:
        print("  Docker ............ OK")
        return True

    if not try_start or sys.platform != "darwin":
        print(f"  Docker ............ FAIL ({err})")
        if sys.platform == "darwin":
            print("    Start Docker: open -a OrbStack  OR  open -a Docker")
        else:
            print("    Start Docker: sudo systemctl start docker")
        return False

    # macOS: attempt to launch a container runtime.
    orbctl = subprocess.run(["which", "orbctl"], capture_output=True, text=True)
    orbstack_app = Path("/Applications/OrbStack.app")
    docker_app = Path("/Applications/Docker.app")

    if orbctl.returncode == 0:
        # orbctl start blocks until the socket is ready.
        print("  Docker ............ starting OrbStack...", flush=True)
        subprocess.run(["orbctl", "start"], capture_output=True, timeout=60)
        ok, _ = _docker_alive()
        if ok:
            print("  Docker ............ OK")
            return True
        # orbctl returned but socket not yet up — fall through to poll.
        print("  Docker ............ polling...", end="", flush=True)
    elif orbstack_app.exists():
        print("  Docker ............ starting OrbStack...", flush=True)
        subprocess.run(["open", "-a", "OrbStack"], check=False)
        print("  Docker ............ polling...", end="", flush=True)
    elif docker_app.exists():
        print("  Docker ............ starting Docker Desktop...", flush=True)
        subprocess.run(["open", "-a", "Docker"], check=False)
        print("  Docker ............ polling...", end="", flush=True)
    else:
        print("  Docker ............ FAIL (no container runtime found)")
        print("    Install OrbStack: https://orbstack.dev  OR  Docker Desktop")
        return False

    deadline = time.time() + 30
    last_err = ""
    while time.time() < deadline:
        ok, last_err = _docker_alive()
        if ok:
            print(" OK")
            return True
        print(".", end="", flush=True)
        time.sleep(2)

    print(f" FAIL ({last_err})")
    return False


def _db_endpoint() -> tuple[str, int]:
    """Read the database host/port from database.yaml, with safe defaults."""
    try:
        import yaml

        config_path = PROJECT_ROOT / "config" / "settings" / "database.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return str(cfg.get("host", "localhost")), int(cfg.get("port", 5432))
    except Exception:
        return "localhost", 5432


def _pg_connect() -> tuple[bool, str]:
    """Attempt one PostgreSQL connection. Returns (ok, detail-or-error)."""
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
        return True, f"{db_cfg.host}:{db_cfg.port}/{db_cfg.name}"
    except Exception as e:
        return False, str(e)


def _prompt_yes(question: str) -> bool:
    """Ask a y/N question. Answers "no" when stdin is not a terminal."""
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _pg_launch_agent() -> str | None:
    """Return the loaded Homebrew launchd label for PostgreSQL, if any."""
    try:
        out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=5
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        label = line.split("\t")[-1].strip()
        if label.startswith("homebrew.mxcl.postgresql"):
            return label
    return None


def _pg_data_dir(label: str) -> Path | None:
    """Read the ``-D`` data directory out of a Homebrew launchd plist."""
    import plistlib

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    try:
        with open(plist_path, "rb") as f:
            argv = plistlib.load(f).get("ProgramArguments", [])
    except Exception:
        return None
    if "-D" in argv:
        idx = argv.index("-D")
        if idx + 1 < len(argv):
            return Path(argv[idx + 1])
    return None


def _clear_stale_pidfile(data_dir: Path) -> None:
    """Remove a postmaster.pid left behind by an unclean shutdown.

    Postgres refuses to start while the lock file exists ("lock file
    postmaster.pid already exists"), even after the PID it names has been
    recycled by an unrelated process. Only removed once that PID is confirmed
    dead or confirmed not to be a postmaster.
    """
    pidfile = data_dir / "postmaster.pid"
    try:
        pid = int(pidfile.read_text().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return

    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    except PermissionError:
        alive = True

    if alive:
        comm = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True
        ).stdout
        if "postgres" in comm:
            return  # a real postmaster owns this data directory

    pidfile.unlink(missing_ok=True)
    print(f"    Removed stale lock file {pidfile} (PID {pid} is not a postmaster)")


def _start_postgres(label: str) -> bool:
    """Kickstart the Homebrew PostgreSQL launch agent and wait for the port."""
    data_dir = _pg_data_dir(label)
    if data_dir is not None:
        _clear_stale_pidfile(data_dir)

    print(f"  PostgreSQL ........ starting {label}...", flush=True)
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        timeout=30,
    )
    host, port = _db_endpoint()
    return _wait_for_tcp(host, port, timeout_sec=20)


def check_postgres(*, try_start: bool = False) -> bool:
    """Check PostgreSQL connectivity using config from database.yaml.

    With ``try_start=True`` on macOS, offers to start the Homebrew-managed
    launch agent when nothing is listening on the database port. The server is
    never started without confirmation — a non-interactive shell just prints
    the command to run.
    """
    ok, detail = _pg_connect()
    if ok:
        print(f"  PostgreSQL ........ OK ({detail})")
        return True

    print(f"  PostgreSQL ........ FAIL ({detail})")

    host, port = _db_endpoint()
    label = _pg_launch_agent() if sys.platform == "darwin" else None
    listening = _wait_for_tcp(host, port, timeout_sec=0.5)

    # Something is already on the port — this is a credentials/database problem,
    # not a stopped server, so starting anything would not help.
    if listening or label is None or not try_start:
        if not listening:
            print("    Start PostgreSQL: brew services start postgresql")
        return False

    if not _prompt_yes(f"    PostgreSQL is not running. Start {label} now?"):
        print(f"    Start PostgreSQL: launchctl kickstart -k gui/{os.getuid()}/{label}")
        return False

    if not _start_postgres(label):
        print("  PostgreSQL ........ FAIL (did not accept connections within 20s)")
        return False

    ok, detail = _pg_connect()
    print(f"  PostgreSQL ........ {f'OK ({detail})' if ok else f'FAIL ({detail})'}")
    return ok


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
    pg_ok = check_postgres(try_start=True)
    docker_ok = check_docker(try_start=True)
    port_ok = check_port_free(backend_port)
    if check_frontend:
        check_port_free(FRONTEND_PORT)

    if not (redis_ok and pg_ok):
        print("\nRequired services are not running. Fix the issues above and retry.")
        return False
    if not port_ok:
        print(
            f"\nPort {backend_port} is in use. Run 'python services.py stop' first or use --port <other>."  # noqa: E501
        )
        return False
    if not docker_ok:
        print("\nWarning: Docker is not available. Container-mode agent execution will not work.")
        print("  Continuing without Docker (local-mode missions will still run).")
    return True


def run_migrations() -> bool:
    """Run alembic upgrade head."""
    print("\nRunning migrations...")
    result = subprocess.run(
        [sys.executable, "admin.py", "migrate", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if result.returncode == 0:
        print("  Migrations ........ OK")
        return True
    else:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"  Migrations ........ FAIL\n    {stderr[:200]}")
        return False


def dev_login_line() -> str:
    """The startup banner's login line, from the credentials the dev user seed creates."""
    from modules.backend.core.exceptions import ValidationError
    from modules.backend.services.bootstrap import BootstrapService

    try:
        email, password = BootstrapService.dev_credentials("admin")
    except ValidationError as e:
        return f"  Login:          not available ({e})"
    return f"  Login:          {email} / {password}"


def ensure_dev_user() -> None:
    """Create dev/test users (sysadmin, admin, user) if they don't exist.

    Delegates to BootstrapService.ensure_dev_users() which handles
    system accounts and all three dev users idempotently.
    """
    print("\nChecking dev users...")

    async def _ensure():
        from modules.backend.services.bootstrap import BootstrapService

        async with BootstrapService.factory() as svc:
            created = await svc.ensure_dev_users()

        if created:
            for user in created:
                print(f"  {user.email} .... CREATED ({user.system_role})")
        else:
            print("  All dev users already exist.")

    asyncio.run(_ensure())
