"""Chat turn activities honour ChatTurnInput.agent_id (Plan 88 Phase 2 failure drill).

A mission run's session belongs to mission.supervisor.agent. The supervisor
wakes the Director on that session through start_director_turn, which sets
ChatTurnInput.agent_id="mission.director.agent". Before the fix the activities
dropped agent_id, so handle() routed by session.agent_id and the supervisor
answered the refine prompt.

The real start_director_turn builds the input and the real _resolve_agent picks
the agent; handle(), Temporal, Redis and the DB session are patched.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from modules.backend.agents.mission_control.helpers.routing import _resolve_agent
from modules.backend.temporal.chat_activities import execute_chat_turn, persist_user_message
from modules.backend.temporal.chat_models import ChatTurnInput
from modules.backend.temporal.mission_run_models import DirectorTurnInput
from modules.backend.temporal.supervisor_activities import start_director_turn

DIRECTOR = "mission.director.agent"
SUPERVISOR = "mission.supervisor.agent"


async def _director_turn_input() -> ChatTurnInput:
    """The ChatTurnInput start_director_turn sends for a run's refine turn."""
    client = MagicMock(start_workflow=AsyncMock())
    with patch(
        "modules.backend.temporal.client.get_temporal_client", AsyncMock(return_value=client)
    ):
        await ActivityEnvironment().run(
            start_director_turn,
            DirectorTurnInput(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "Please call refine_plan",
                "mission-run-parent",
            ),
        )
    return client.start_workflow.await_args.args[1]


@asynccontextmanager
async def _db():
    yield SimpleNamespace(commit=AsyncMock())


async def test_director_followup_on_run_session_answered_by_director():
    inp = await _director_turn_input()
    run_session = SimpleNamespace(agent_id=SUPERVISOR)
    registry = SimpleNamespace(has=lambda name: name in {DIRECTOR, SUPERVISOR})
    handle_kwargs: dict = {}

    async def fake_handle(session_id: str, message: str, **kwargs):
        handle_kwargs.update(kwargs)
        agent = _resolve_agent(run_session, message, target_agent=kwargs.get("target_agent"))
        yield SimpleNamespace(agent_id=agent, full_content=f"answered by {agent}")

    with (
        patch("modules.backend.agents.mission_control.mission_control.handle", fake_handle),
        patch(
            "modules.backend.agents.mission_control.helpers.routing.get_registry",
            return_value=registry,
        ),
        patch("redis.asyncio.Redis.from_url", return_value=MagicMock(aclose=AsyncMock())),
        patch("modules.backend.core.config.get_redis_url", return_value="redis://test"),
        patch("modules.backend.core.database.get_async_session", _db),
    ):
        result = await ActivityEnvironment().run(execute_chat_turn, inp)

    assert result.error is None
    assert handle_kwargs["target_agent"] == DIRECTOR
    assert result.agent_name == DIRECTOR


async def test_director_followup_user_message_targets_director():
    inp = await _director_turn_input()
    add_message = AsyncMock()

    with (
        patch("modules.backend.core.database.get_async_session", _db),
        patch("modules.backend.services.session.SessionService.add_message", add_message),
    ):
        await ActivityEnvironment().run(persist_user_message, inp)

    assert add_message.await_args.kwargs["target_agent"] == DIRECTOR
    assert add_message.await_args.args[1].sender_id == SUPERVISOR
