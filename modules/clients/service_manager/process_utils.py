"""Process, port, and daemon-readiness utilities.

Split out of root services.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from modules.clients.service_manager.constants import (
    DAEMON_LOG_TAIL_BYTES,
    DAEMON_START_TIMEOUT_SEC,
    FRONTEND_PORT,
    SERVICE_LOG_DIR,
    TEMPORAL_NAMESPACE,
    TEMPORAL_PORT,
    TEMPORAL_START_TIMEOUT_SEC,
)


def get_pids_on_port(port: int) -> list[int]:
    """Return PIDs listening on a port."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-t"],
            capture_output=True,
            text=True,
            timeout=3,
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
        print(
            f"  {label}: sent SIGTERM to {killed} process(es) (PID {', '.join(str(p) for p in pids)})"  # noqa: E501
        )

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


def _wait_for_temporal(log_path: Path | None = None) -> bool:
    """Block until the Temporal dev server can serve workflow clients.

    Binding the port is not enough — ``start-dev`` accepts TCP before it has
    registered the default namespace, and a worker that connects in that window
    dies on startup. Readiness is therefore "namespace describe succeeds".
    """
    if not _wait_for_tcp("localhost", TEMPORAL_PORT, timeout_sec=TEMPORAL_START_TIMEOUT_SEC):
        print(f"  Temporal .......... FAIL (port {TEMPORAL_PORT} not accepting connections)")
        if log_path is not None:
            print(_read_log_tail(log_path))
        return False

    deadline = time.monotonic() + TEMPORAL_START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            probe = subprocess.run(
                [
                    "temporal",
                    "operator",
                    "namespace",
                    "describe",
                    "-n",
                    TEMPORAL_NAMESPACE,
                    "--address",
                    f"localhost:{TEMPORAL_PORT}",
                ],
                capture_output=True,
                timeout=15,
            )
        except FileNotFoundError:
            print("  Temporal .......... FAIL (temporal CLI not found on PATH)")
            print("    Install: brew install temporal")
            return False
        except subprocess.TimeoutExpired:
            # Server is still coming up and left the RPC hanging — keep polling
            # until the overall deadline rather than giving up on one slow call.
            continue
        if probe.returncode == 0:
            return True
        time.sleep(0.5)

    print(f"  Temporal .......... FAIL (namespace '{TEMPORAL_NAMESPACE}' not ready)")
    if log_path is not None:
        print(_read_log_tail(log_path))
    return False


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
