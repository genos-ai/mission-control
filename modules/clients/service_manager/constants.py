"""Shared constants for the service manager (Plan 84 Phase 5.5).

Computes its own PROJECT_ROOT independently rather than importing it
from services.py, since services.py needs a project root value before
it can perform the sys.path bootstrap that makes this import possible.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read_backend_port() -> int:
    """Read backend port from config/settings/application.yaml.

    Uses raw YAML parsing (no backend imports) so services.py works
    even before the backend is fully installed.
    """
    try:
        import yaml

        config_path = PROJECT_ROOT / "config" / "settings" / "application.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return int(cfg.get("server", {}).get("port", 8100))
    except Exception:
        return 8100


BACKEND_PORT = _read_backend_port()
DEFAULT_BIND_HOST = "0.0.0.0"  # backend bind address unless --host overrides it
FRONTEND_PORT = 5174  # defined in modules/frontend/vite.config.ts
TEMPORAL_PORT = 7233
TEMPORAL_UI_PORT = 8233
# Same path Plan 89 uses when it starts Temporal by hand, so both share one store.
TEMPORAL_DB_FILE = PROJECT_ROOT / "var" / "temporal" / "temporal.db"

# Log directory aligns with application logging (var/logs).
SERVICE_LOG_DIR = PROJECT_ROOT / "var" / "logs"
DAEMON_START_TIMEOUT_SEC = 90.0
DAEMON_LOG_TAIL_BYTES = 8000
TEMPORAL_START_TIMEOUT_SEC = 45.0
TEMPORAL_WORKER_MODULE = "modules.backend.temporal.worker"  # python -m target; also the stop match
TEMPORAL_NAMESPACE = "default"  # must match config/settings/temporal.yaml
