"""services.py command line: SERVICE argument, validation, tree and help output."""

import sys
from unittest.mock import patch

import pytest

import services
from modules.clients.service_manager.registry import SERVICE_NAMES, ServiceContext


def _parse(*argv: str):
    with patch.object(sys, "argv", ["services.py", *argv]):
        return services._build_parser().parse_args()


@pytest.mark.parametrize("command", ["start", "stop", "restart"])
def test_commands_accept_service_names(command):
    assert _parse(command, "api", "worker").services == ["api", "worker"]


@pytest.mark.parametrize("command", ["start", "stop", "restart"])
def test_service_names_default_to_empty(command):
    assert _parse(command).services == []


def test_unknown_service_is_rejected(capsys):
    with pytest.raises(SystemExit):
        _parse("restart", "bogus")
    assert "invalid service 'bogus'" in capsys.readouterr().err


def test_backend_only_cannot_be_combined_with_named_services(capsys):
    argv = ["services.py", "stop", "api", "--backend-only"]
    with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
        services.main()
    assert "cannot be combined" in capsys.readouterr().err


def test_tree_documents_the_service_argument_and_every_service(capsys):
    services.cmd_tree(None)
    out = capsys.readouterr().out
    for command in ("start", "stop", "restart"):
        line = next(line for line in out.splitlines() if f"── {command} " in line)
        assert "[SERVICE ...]" in line
        assert all(name in line for name in SERVICE_NAMES)


def test_stop_of_named_services_refuses_a_foreground_session(capsys):
    args = _parse("stop", "worker")
    with (
        patch.object(services, "find_foreground_supervisor", return_value=4242),
        patch.object(services, "stop_services") as stop,
        pytest.raises(SystemExit),
    ):
        services.cmd_stop(args)
    stop.assert_not_called()
    assert "4242" in capsys.readouterr().out


def test_full_stop_does_not_check_for_a_foreground_session():
    args = _parse("stop")
    with (
        patch.object(services, "find_foreground_supervisor") as guard,
        patch.object(services, "stop_services", return_value=0),
    ):
        services.cmd_stop(args)
    guard.assert_not_called()


def test_named_start_skips_preflight_and_starts_only_those_services():
    args = _parse("start", "worker", "api")
    with (
        patch.object(services, "preflight") as preflight,
        patch.object(services, "start_services") as start,
    ):
        services.cmd_start(args)
    preflight.assert_not_called()
    (selected, ctx), _ = start.call_args
    assert [s.name for s in selected] == ["api", "worker"]
    assert isinstance(ctx, ServiceContext)
