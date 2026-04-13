"""
Unit Tests for Session Event Bus.

Tests SessionEventBus publish/subscribe against real Redis (P12).
All events go through mission_events:{mission_id} — one channel per mission.
"""

import asyncio
import json
import uuid

import pytest
from redis.asyncio import Redis as AsyncRedis

from modules.backend.events.bus import SessionEventBus
from modules.backend.events.types import AgentThinkingEvent, UserMessageEvent


MISSION_ID = "test-mission-" + uuid.uuid4().hex[:8]
SESSION_ID = uuid.uuid4()


@pytest.fixture
def bus(redis: AsyncRedis) -> SessionEventBus:
    """Create a SessionEventBus backed by real Redis with a test mission_id."""
    return SessionEventBus(redis, mission_id=MISSION_ID)


class TestPublish:
    """Test event publishing to real Redis Pub/Sub."""

    @pytest.mark.asyncio
    async def test_publish_sends_json_to_mission_channel(self, bus: SessionEventBus, redis: AsyncRedis):
        """Published event should be valid JSON on the mission channel."""
        event = AgentThinkingEvent(
            session_id=SESSION_ID,
            source="agent:health",
            agent_id="platform.health.agent",
        )

        pubsub = redis.pubsub()
        channel = f"mission_events:{MISSION_ID}"
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)

        await bus.publish(event)

        message = await pubsub.get_message(timeout=2.0)
        assert message is not None
        assert message["type"] == "message"

        data = json.loads(message["data"])
        assert data["event_type"] == "agent.thinking.started"
        assert data["agent_id"] == "platform.health.agent"
        assert data["session_id"] == str(SESSION_ID)

        await pubsub.unsubscribe(channel)
        await pubsub.close()

    @pytest.mark.asyncio
    async def test_publish_to_mission_uses_explicit_mission_id(self, bus: SessionEventBus, redis: AsyncRedis):
        """publish_to_mission() should publish to the specified mission channel."""
        other_mission = "other-mission-" + uuid.uuid4().hex[:8]
        event = AgentThinkingEvent(
            session_id=SESSION_ID,
            source="agent:health",
            agent_id="platform.health.agent",
        )
        expected_channel = f"mission_events:{other_mission}"

        pubsub = redis.pubsub()
        await pubsub.subscribe(expected_channel)
        await pubsub.get_message(timeout=1.0)

        await bus.publish_to_mission(other_mission, event)

        message = await pubsub.get_message(timeout=2.0)
        assert message is not None
        assert message["channel"].decode() == expected_channel

        await pubsub.unsubscribe(expected_channel)
        await pubsub.close()

    @pytest.mark.asyncio
    async def test_publish_without_mission_id_drops_event(self, redis: AsyncRedis):
        """Bus without mission_id should log warning and drop the event."""
        bus_no_mission = SessionEventBus(redis)
        event = AgentThinkingEvent(
            session_id=SESSION_ID,
            source="agent:health",
            agent_id="platform.health.agent",
        )
        # Should not raise — just drops silently
        await bus_no_mission.publish(event)


class TestSubscribe:
    """Test event subscription from real Redis Pub/Sub."""

    @pytest.mark.asyncio
    async def test_subscribe_mission_receives_typed_event(self, bus: SessionEventBus, redis: AsyncRedis):
        """Subscribed events should deserialize to the correct subclass."""
        event = UserMessageEvent(
            session_id=SESSION_ID,
            source="human",
            content="Hello agent",
            channel="tui",
        )

        received: list = []

        async def collect_events():
            async for evt in bus.subscribe_mission(MISSION_ID):
                received.append(evt)
                break

        task = asyncio.create_task(collect_events())
        await asyncio.sleep(0.1)

        await bus.publish(event)

        await asyncio.wait_for(task, timeout=3.0)

        assert len(received) == 1
        assert isinstance(received[0], UserMessageEvent)
        assert received[0].content == "Hello agent"
        assert received[0].session_id == SESSION_ID

    @pytest.mark.asyncio
    async def test_subscribe_filtered_only_yields_matching_session(self, bus: SessionEventBus, redis: AsyncRedis):
        """subscribe_mission_filtered should only yield events for the target session."""
        other_session = uuid.uuid4()
        target_event = AgentThinkingEvent(
            session_id=SESSION_ID, source="agent:health", agent_id="target",
        )
        other_event = AgentThinkingEvent(
            session_id=other_session, source="agent:health", agent_id="other",
        )

        received: list = []

        async def collect_events():
            async for evt in bus.subscribe_mission_filtered(MISSION_ID, SESSION_ID):
                received.append(evt)
                break

        task = asyncio.create_task(collect_events())
        await asyncio.sleep(0.1)

        await bus.publish(other_event)  # should be filtered out
        await bus.publish(target_event)  # should be yielded

        await asyncio.wait_for(task, timeout=3.0)

        assert len(received) == 1
        assert received[0].agent_id == "target"

    @pytest.mark.asyncio
    async def test_subscribe_receives_multiple_events_in_order(self, bus: SessionEventBus, redis: AsyncRedis):
        """Multiple events published to the same mission arrive in order."""
        events = [
            AgentThinkingEvent(session_id=SESSION_ID, source="agent:health", agent_id="agent-1"),
            AgentThinkingEvent(session_id=SESSION_ID, source="agent:health", agent_id="agent-2"),
            AgentThinkingEvent(session_id=SESSION_ID, source="agent:health", agent_id="agent-3"),
        ]

        received: list = []

        async def collect_events():
            async for evt in bus.subscribe_mission(MISSION_ID):
                received.append(evt)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(collect_events())
        await asyncio.sleep(0.1)

        for event in events:
            await bus.publish(event)

        await asyncio.wait_for(task, timeout=3.0)

        assert len(received) == 3
        assert [e.agent_id for e in received] == ["agent-1", "agent-2", "agent-3"]
