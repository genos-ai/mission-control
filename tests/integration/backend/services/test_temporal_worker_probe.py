"""count_task_queue_pollers against a real Temporal server and a real worker.

Needs the Temporal dev server the platform starts (`services.py start`); skipped when none
answers. A throwaway task queue is used, so the platform's own queue is never touched.
"""

import asyncio
import uuid

import pytest
from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.backend.core.config import get_app_config
from modules.backend.services.health import count_task_queue_pollers


@workflow.defn
class _Noop:
    @workflow.run
    async def run(self) -> None:
        return None


@pytest.fixture
async def temporal():
    config = get_app_config().temporal
    try:
        client = await asyncio.wait_for(
            Client.connect(config.server_url, namespace=config.namespace), 3
        )
        await asyncio.wait_for(client.service_client.check_health(), 3)
    except Exception as exc:
        pytest.skip(f"No Temporal server at {config.server_url}: {exc}")
    return client, config.namespace


async def test_a_queue_nobody_polls_has_no_pollers(temporal):
    client, namespace = temporal

    assert await count_task_queue_pollers(client, namespace, f"health-test-{uuid.uuid4()}") == 0


async def test_a_running_worker_is_counted(temporal):
    client, namespace = temporal
    queue = f"health-test-{uuid.uuid4()}"

    # Unsandboxed: the sandbox re-imports this pytest module, which it cannot validate.
    async with Worker(
        client, task_queue=queue, workflows=[_Noop], workflow_runner=UnsandboxedWorkflowRunner()
    ):
        pollers = 0
        for _ in range(50):  # a poller registers within a moment of the worker starting
            pollers = await count_task_queue_pollers(client, namespace, queue)
            if pollers:
                break
            await asyncio.sleep(0.1)

    assert pollers >= 1
