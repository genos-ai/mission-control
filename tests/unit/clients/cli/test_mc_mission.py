"""Tests for `mc mission create` (Plan 88 step 88.1.0).

The gate mode travels in the POST /missions body; no follow-up PATCH /plan.
"""

from unittest.mock import AsyncMock

import pytest

from modules.clients.cli.mc_mission import create

USER_ID = "11111111-1111-1111-1111-111111111111"
MISSION_ID = "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_create_sends_gate_mode_in_post():
    api = AsyncMock()
    api.get = AsyncMock(return_value={"id": USER_ID})
    api.post = AsyncMock(return_value={"id": MISSION_ID, "name": "gate-test"})
    api.patch = AsyncMock()

    await create(api, name="gate-test", description="Gate test", gate_mode="autonomous")

    api.post.assert_awaited_once()
    assert api.post.await_args.args[0] == "/missions"
    assert api.post.await_args.kwargs["body"]["gate_mode"] == "autonomous"
    api.patch.assert_not_awaited()
