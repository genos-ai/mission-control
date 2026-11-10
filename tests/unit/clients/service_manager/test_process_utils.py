"""Process discovery and stop helpers (dev service manager)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psutil

from modules.clients.service_manager import process_utils
from modules.clients.service_manager.process_utils import (
    find_foreground_supervisor,
    get_pids_by_cmdline,
    get_pids_on_port,
    stop_processes,
    temporal_db_args,
)


def test_get_pids_on_port_only_asks_for_listeners():
    completed = SimpleNamespace(returncode=0, stdout="10\n11\n")
    with patch.object(process_utils.subprocess, "run", return_value=completed) as run:
        assert get_pids_on_port(7233) == [10, 11]
    assert run.call_args.args[0] == ["lsof", "-iTCP:7233", "-sTCP:LISTEN", "-t"]


def test_get_pids_by_cmdline_matches_fragment_and_skips_own_process():
    own = process_utils.os.getpid()
    procs = [
        SimpleNamespace(pid=own, info={"cmdline": ["python", "-m", "target.module"]}),
        SimpleNamespace(pid=7, info={"cmdline": ["python", "-m", "target.module"]}),
        SimpleNamespace(pid=8, info={"cmdline": ["python", "-m", "other"]}),
        SimpleNamespace(pid=9, info={"cmdline": None}),
    ]
    with patch.object(psutil, "process_iter", return_value=procs):
        assert get_pids_by_cmdline("target.module") == [7]


def test_stop_processes_retries_until_nothing_is_left():
    found = [[5], [6], []]
    with (
        patch.object(process_utils, "kill_pids", return_value=1) as kill,
        patch.object(process_utils.time, "sleep"),
    ):
        assert stop_processes(lambda: found.pop(0), "Svc") == 2
    assert kill.call_count == 2


def test_stop_processes_is_a_no_op_when_nothing_runs():
    with patch.object(process_utils, "kill_pids") as kill:
        assert stop_processes(lambda: [], "Svc") == 0
    kill.assert_not_called()


def _process_with_ancestors(*cmdlines: list[str], pids: tuple[int, ...]) -> MagicMock:
    ancestors = [
        SimpleNamespace(pid=pid, cmdline=lambda c=cmdline: c)
        for pid, cmdline in zip(pids, cmdlines)
    ]
    proc = MagicMock()
    proc.parents.return_value = ancestors
    return proc


def test_foreground_session_is_detected_through_its_ancestors():
    proc = _process_with_ancestors(
        ["python", "-m", "uvicorn"], ["python", "services.py", "start"], pids=(100, 200)
    )
    with patch.object(psutil, "Process", return_value=proc):
        assert find_foreground_supervisor([1]) == 200


def test_foreground_restart_session_is_detected():
    proc = _process_with_ancestors(["python", "/repo/services.py", "restart"], pids=(300,))
    with patch.object(psutil, "Process", return_value=proc):
        assert find_foreground_supervisor([1]) == 300


def test_daemon_started_services_are_not_foreground():
    proc = _process_with_ancestors(["python", "services.py", "start", "--daemon"], pids=(200,))
    with patch.object(psutil, "Process", return_value=proc):
        assert find_foreground_supervisor([1]) is None


def test_unrelated_ancestors_are_not_foreground():
    proc = _process_with_ancestors(["zsh"], ["python", "other.py", "start"], pids=(1, 2))
    with patch.object(psutil, "Process", return_value=proc):
        assert find_foreground_supervisor([1]) is None


def test_foreground_check_ignores_processes_that_already_exited():
    with patch.object(psutil, "Process", side_effect=psutil.NoSuchProcess(1)):
        assert find_foreground_supervisor([1]) is None


def test_temporal_db_args_creates_the_directory(tmp_path: Path):
    db_file = tmp_path / "nested" / "temporal.db"
    with patch.object(process_utils, "TEMPORAL_DB_FILE", db_file):
        assert temporal_db_args() == ["--db-filename", str(db_file)]
    assert db_file.parent.is_dir()
