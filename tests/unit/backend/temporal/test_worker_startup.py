"""Worker startup fails closed without the digest agent (Plan 88, 88.3.6, contract 3.4.6)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import NotFoundError

WORKER = "modules.backend.temporal.worker"


def _catalog(get_by_name: AsyncMock):
    @asynccontextmanager
    async def _factory():
        yield SimpleNamespace(get_by_name=get_by_name)

    return _factory


@pytest.fixture
def worker_cls(monkeypatch) -> MagicMock:
    monkeypatch.setattr(f"{WORKER}.get_temporal_config", lambda: SimpleNamespace(task_queue="q"))
    monkeypatch.setattr(f"{WORKER}.get_temporal_client", AsyncMock(return_value=object()))
    cls = MagicMock(name="Worker")
    monkeypatch.setattr(f"{WORKER}.Worker", cls)
    return cls


async def test_worker_refuses_start_without_digest_agent(monkeypatch, worker_cls):
    from modules.backend.temporal.worker import start_worker

    get_by_name = AsyncMock(side_effect=NotFoundError("missing"))
    monkeypatch.setattr(f"{WORKER}.AgentCatalogService.factory", _catalog(get_by_name))

    with pytest.raises(NotFoundError):
        await start_worker()

    get_by_name.assert_awaited_once_with(get_app_config().missions.digest.agent_name)
    worker_cls.assert_not_called()


async def test_worker_checks_digest_agent_before_constructing_worker(monkeypatch, worker_cls):
    from modules.backend.temporal.worker import start_worker

    order: list[str] = []
    get_by_name = AsyncMock(side_effect=lambda name: order.append("catalog"))
    monkeypatch.setattr(f"{WORKER}.AgentCatalogService.factory", _catalog(get_by_name))

    def _construct(*_args, **_kwargs):
        order.append("worker")
        raise RuntimeError("stop after construction")

    worker_cls.side_effect = _construct

    with pytest.raises(RuntimeError, match="stop after construction"):
        await start_worker()

    assert order == ["catalog", "worker"]
