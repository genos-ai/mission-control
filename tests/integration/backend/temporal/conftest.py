"""Temporal integration fixtures (Plan 88 step 88.1.5)."""

from collections.abc import AsyncGenerator

import pytest
from temporalio.testing import WorkflowEnvironment


@pytest.fixture(scope="session")
async def temporal_env() -> AsyncGenerator[WorkflowEnvironment, None]:
    """A local Temporal dev server for the session; the binary is prefetched in CI by 88.0.1."""
    env = await WorkflowEnvironment.start_local(namespace="default")
    try:
        yield env
    finally:
        await env.shutdown()
