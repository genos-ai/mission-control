"""Service registry: selection, start order, stop order (dev service manager)."""

from unittest.mock import MagicMock, patch

import pytest

from modules.clients.service_manager import registry
from modules.clients.service_manager.registry import (
    SERVICE_NAMES,
    ManagedService,
    ServiceContext,
    resolve_services,
    start_services,
    stop_services,
)

CTX = ServiceContext(port=8100)


def _service(name: str, pids: list[int], start: MagicMock | None = None) -> ManagedService:
    return ManagedService(
        name=name,
        label=lambda ctx: name.title(),
        find_pids=lambda ctx: pids,
        start=start or MagicMock(),
    )


def test_resolve_defaults_to_every_service_in_start_order():
    assert [s.name for s in resolve_services()] == list(SERVICE_NAMES)
    assert SERVICE_NAMES == ("temporal", "api", "worker", "frontend")


def test_resolve_can_exclude_the_frontend():
    names = [s.name for s in resolve_services(include_frontend=False)]
    assert names == ["temporal", "api", "worker"]


def test_resolve_returns_named_services_in_start_order_without_duplicates():
    names = [s.name for s in resolve_services(["worker", "api", "worker"])]
    assert names == ["api", "worker"]


def test_resolve_rejects_unknown_names():
    with pytest.raises(ValueError, match="bogus"):
        resolve_services(["api", "bogus"])


def test_start_skips_running_services_and_starts_the_rest_in_order():
    calls: list[str] = []
    running = _service("api", [1234])
    stopped_a = _service("temporal", [], MagicMock(side_effect=lambda ctx: calls.append("a")))
    stopped_b = _service("worker", [], MagicMock(side_effect=lambda ctx: calls.append("b")))

    start_services([stopped_a, running, stopped_b], CTX)

    assert calls == ["a", "b"]
    running.start.assert_not_called()


def test_stop_runs_in_reverse_of_start_order():
    order: list[str] = []
    services = [_service("temporal", [1]), _service("api", [2]), _service("worker", [3])]

    def fake_stop(find_pids, label):
        order.append(label)
        return 1

    with patch.object(registry, "stop_processes", fake_stop):
        total = stop_services(services, CTX)

    assert order == ["Worker", "Api", "Temporal"]
    assert total == 3


def test_worker_is_found_by_command_line_not_port():
    worker = next(s for s in registry.SERVICES if s.name == "worker")
    with patch.object(registry, "get_pids_by_cmdline", return_value=[42]) as by_cmdline:
        assert worker.find_pids(CTX) == [42]
    by_cmdline.assert_called_once_with(registry.TEMPORAL_WORKER_MODULE)
