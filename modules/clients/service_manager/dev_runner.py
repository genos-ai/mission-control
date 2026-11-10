"""_backend_command + DevRunner: interactive (non-daemon) dev process management.

Split out of root services.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import subprocess
import sys
import time

from modules.clients.service_manager.constants import (
    BACKEND_PORT,
    PROJECT_ROOT,
    SERVICE_LOG_DIR,
    TEMPORAL_PORT,
    TEMPORAL_UI_PORT,
)
from modules.clients.service_manager.process_utils import get_pids_on_port, temporal_db_args


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
        # SSE endpoints (streams.py) hold connections open indefinitely.
        # Without a graceful-shutdown timeout, uvicorn hangs at
        # "Waiting for connections to close" until every browser tab
        # with an EventSource disconnects. 5s is enough for normal
        # requests to drain; SSE generators catch CancelledError and
        # clean up Redis subscriptions in their finally blocks.
        "--timeout-graceful-shutdown",
        "5",
    ]
    if reload:
        cmd.extend(
            [
                "--reload",
                "--reload-dir",
                "modules/backend",
                "--reload-dir",
                "config",
            ]
        )
    return cmd


class DevRunner:
    """Manages backend and frontend subprocesses."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []
        self._shutting_down = False
        self._backend_proc: subprocess.Popen | None = None
        self._reload_enabled = False

    def start_backend(self, host: str, port: int, reload: bool) -> subprocess.Popen:
        self._reload_enabled = reload
        proc = subprocess.Popen(
            _backend_command(host, port, reload=reload),
            cwd=PROJECT_ROOT,
        )
        self._backend_proc = proc
        self.procs.append(proc)
        return proc

    def start_temporal_server(self) -> subprocess.Popen:
        """Launch the Temporal dev server, tee-ing its output to var/logs.

        Output goes to a file rather than DEVNULL so a failed start leaves
        something to read — the server is otherwise silent about why it died.
        The log is truncated per run so a failure tail shows this start, not
        months of accumulated dev-server chatter.
        """
        SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_handle = open(SERVICE_LOG_DIR / "services-temporal.log", "wb")
        proc = subprocess.Popen(
            [
                "temporal",
                "server",
                "start-dev",
                "--port",
                str(TEMPORAL_PORT),
                "--ui-port",
                str(TEMPORAL_UI_PORT),
                *temporal_db_args(),
                "--log-format",
                "pretty",
            ],
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        log_handle.close()
        self.procs.append(proc)
        return proc

    def start_temporal_worker(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-m", "modules.backend.temporal.worker"],
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
        """Block until any child exits or Ctrl-C.

        With --reload, uvicorn's reloader kills and respawns workers
        internally. If the supervisor process itself exits (e.g. code -9
        during a reload cycle), check whether something is still
        listening on the port before declaring death — the reloader may
        have already respawned. This check only applies to the backend
        process; any other process exiting (e.g. frontend npm) is fatal.
        """
        try:
            while True:
                for proc in list(self.procs):
                    ret = proc.poll()
                    if ret is not None:
                        name = (
                            " ".join(proc.args[:4])
                            if isinstance(proc.args, list)
                            else str(proc.args)
                        )
                        # With --reload, the backend supervisor may exit
                        # transiently. Only ignore if it's the backend
                        # AND the port is still occupied (respawned).
                        is_backend = proc is self._backend_proc
                        if is_backend and self._reload_enabled and get_pids_on_port(BACKEND_PORT):
                            print(
                                f"\nBackend process exited (code {ret}) — reloader respawned. Continuing."  # noqa: E501
                            )
                            self.procs.remove(proc)
                            self._backend_proc = None
                            continue
                        print(f"\nProcess exited (code {ret}): {name}")
                        self.shutdown()
                        return ret
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.shutdown()
            return 0
