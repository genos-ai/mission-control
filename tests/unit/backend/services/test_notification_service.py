"""NotificationService.notify (Plan 88 step 88.4.4, contracts 3.5.1, 3.1.10 and 3.6.2).

Per P12 these run against the test database (transaction rolled back per test).
Telegram is a real TelegramAdapter over a mocked aiogram Bot; Redis SSE is
captured by patching the module's publisher.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.core.utils import utc_now
from modules.backend.gateway.adapters.telegram import TelegramAdapter
from modules.backend.models.action_token import ActionToken
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission import Mission
from modules.backend.models.notification import (
    MissionNotificationRecipient,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationKind,
)
from modules.backend.models.user_channel_identity import (
    ChannelKind,
    UserChannelIdentity,
)
from modules.backend.services import notification as notification_module
from modules.backend.services.mission import MissionService
from modules.backend.services.notification import NotificationService
from modules.backend.temporal.mission_run_models import NotificationRequest
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2

OWNER_CHAT = 1001
MEMBER_CHAT = 1002


@pytest.fixture(autouse=True)
async def _ensure_test_users(test_user, test_user_2):
    """Recipients and identities FK to users."""


class FakeBus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_to_mission(self, mission_id: str, event) -> None:
        self.events.append(event)


@pytest.fixture
def bot() -> MagicMock:
    bot = MagicMock()
    counter = iter(range(1, 1000))
    bot.send_message = AsyncMock(side_effect=lambda **kw: SimpleNamespace(message_id=next(counter)))
    return bot


@pytest.fixture
def sse(monkeypatch) -> list[tuple[str, dict]]:
    published: list[tuple[str, dict]] = []

    async def _publish(mission_id: str, message: dict) -> None:
        published.append((mission_id, message))

    monkeypatch.setattr(notification_module, "_publish_sse", _publish)
    return published


@pytest.fixture
def adapter(monkeypatch, bot) -> TelegramAdapter:
    telegram = TelegramAdapter(bot=bot)
    monkeypatch.setattr(notification_module, "get_adapter", lambda name: telegram)
    return telegram


def _config(monkeypatch, *, enabled=True, telegram=True, inbound=False, max_chars=None) -> None:
    base = get_app_config().notifications
    channels = base.channels.model_copy(
        update={
            "telegram": base.channels.telegram.model_copy(
                update={"enabled": telegram, "inbound_approvals_enabled": inbound}
            )
        }
    )
    update: dict = {"enabled": enabled, "channels": channels}
    if max_chars is not None:
        update["message_max_chars"] = max_chars
    notifications = base.model_copy(update=update)
    fake = SimpleNamespace(notifications=notifications)
    monkeypatch.setattr(notification_module, "get_app_config", lambda: fake)
    monkeypatch.setattr("modules.backend.gateway.adapters.telegram.get_app_config", lambda: fake)


async def _mission(db: AsyncSession, name: str | None = None) -> Mission:
    """A mission owned by TEST_USER_ID; create_mission adds the owner TELEGRAM recipient."""
    return await MissionService(db).create_mission(
        gate_mode="manual",
        name=name or f"notify-{uuid7()}",
        description="notifications",
        owner_id=TEST_USER_ID,
    )


async def _identity(db: AsyncSession, user_id: str, chat_id: int, *, verified: bool = True):
    db.add(
        UserChannelIdentity(
            user_id=user_id,
            channel=ChannelKind.TELEGRAM,
            external_id=str(chat_id),
            verified_at=utc_now() if verified else None,
        )
    )
    await db.flush()


async def _add_member_recipient(db: AsyncSession, mission: Mission, role: str) -> None:
    await MissionService(db).add_member(mission.id, TEST_USER_ID_2, role=role)
    db.add(
        MissionNotificationRecipient(
            mission_id=mission.id,
            user_id=TEST_USER_ID_2,
            channel=ChannelKind.TELEGRAM,
            kinds=[k.value for k in NotificationKind],
        )
    )
    await db.flush()


async def _gate(db: AsyncSession, mission: Mission) -> str:
    gate = GateRequest(
        mission_id=mission.id,
        gate_type="post_run",
        context_json={},
        status=GateRequestStatus.PENDING,
        created_at=utc_now(),
    )
    db.add(gate)
    await db.flush()
    return gate.id


def _request(mission: Mission, kind: NotificationKind, **kw) -> NotificationRequest:
    payload = kw.pop("payload", {"sequence": 3, "status": "failed", "cost_usd": 0.25})
    return NotificationRequest(
        kind=kind.value,
        mission_id=mission.id,
        mission_run_id=None,
        gate_request_id=kw.pop("gate_request_id", None),
        subject_id=kw.pop("subject_id", f"subject-{uuid7()}"),
        payload=payload,
    )


async def _deliveries(db: AsyncSession, mission: Mission) -> list[NotificationDelivery]:
    rows = await db.execute(
        select(NotificationDelivery)
        .where(NotificationDelivery.mission_id == mission.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


async def test_notify_dedupes_on_sent(db_session, adapter, bot, sse, monkeypatch) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    service = NotificationService(db_session, event_bus=FakeBus())
    request = _request(mission, NotificationKind.RUN_FAILED)

    [first] = await service.notify(request)
    [second] = await service.notify(request)

    assert bot.send_message.await_count == 1
    assert first.id == second.id
    assert second.status == NotificationDeliveryStatus.SENT
    assert second.attempt_count == 1
    assert second.provider_message_ref == f"{OWNER_CHAT}:1"


async def test_notify_skips_without_identity(db_session, adapter, bot, sse, monkeypatch) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)

    [delivery] = await NotificationService(db_session, event_bus=FakeBus()).notify(
        _request(mission, NotificationKind.RUN_SUCCEEDED)
    )

    assert delivery.status == NotificationDeliveryStatus.SKIPPED_NO_IDENTITY
    bot.send_message.assert_not_awaited()


async def test_notify_skips_unconfirmed_identity(
    db_session, adapter, bot, sse, monkeypatch
) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT, verified=False)

    [delivery] = await NotificationService(db_session, event_bus=FakeBus()).notify(
        _request(mission, NotificationKind.RUN_SUCCEEDED)
    )

    assert delivery.status == NotificationDeliveryStatus.SKIPPED_NO_IDENTITY
    bot.send_message.assert_not_awaited()


@pytest.mark.parametrize(
    ("enabled", "telegram", "registered"),
    [(False, True, True), (True, False, True), (True, True, False)],
)
async def test_notify_disabled_channel_skips(
    db_session, adapter, bot, sse, monkeypatch, enabled, telegram, registered
) -> None:
    _config(monkeypatch, enabled=enabled, telegram=telegram)
    if not registered:
        monkeypatch.setattr(notification_module, "get_adapter", lambda name: None)
    mission = await _mission(db_session)
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)

    [delivery] = await NotificationService(db_session, event_bus=FakeBus()).notify(
        _request(mission, NotificationKind.RUN_FAILED)
    )

    assert delivery.status == NotificationDeliveryStatus.SKIPPED_DISABLED
    bot.send_message.assert_not_awaited()


def _markup(bot: MagicMock, chat_id: int):
    for call in bot.send_message.await_args_list:
        if call.kwargs["chat_id"] == chat_id:
            return call.kwargs["reply_markup"]
    raise AssertionError(f"no message to {chat_id}")


async def test_gate_waiting_buttons_only_for_operators_with_inbound_enabled(
    db_session, adapter, bot, sse, monkeypatch
) -> None:
    mission = await _mission(db_session)
    await _add_member_recipient(db_session, mission, role="viewer")
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    await _identity(db_session, TEST_USER_ID_2, MEMBER_CHAT)
    gate_id = await _gate(db_session, mission)
    service = NotificationService(db_session, event_bus=FakeBus())

    # Inbound approvals off: no buttons for anyone.
    _config(monkeypatch, inbound=False)
    await service.notify(_request(mission, NotificationKind.GATE_WAITING, gate_request_id=gate_id))
    assert _markup(bot, OWNER_CHAT) is None
    assert _markup(bot, MEMBER_CHAT) is None

    # Inbound on: the owner (operator) gets Approve/Reject, the viewer does not.
    bot.send_message.reset_mock()
    _config(monkeypatch, inbound=True)
    await service.notify(
        _request(mission, NotificationKind.GATE_ESCALATED, gate_request_id=gate_id)
    )
    markup = _markup(bot, OWNER_CHAT)
    [row] = markup.inline_keyboard
    assert [b.text for b in row] == ["Approve", "Reject"]
    assert row[0].callback_data.startswith("g:") and row[0].callback_data.endswith(":a")
    assert row[1].callback_data.endswith(":r")
    assert _markup(bot, MEMBER_CHAT) is None
    tokens = (
        (
            await db_session.execute(
                select(ActionToken).where(ActionToken.gate_request_id == gate_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(tokens) == 2
    assert {t.user_id for t in tokens} == {TEST_USER_ID}
    assert all(
        t.channel_message_ref and t.channel_message_ref.startswith(f"{OWNER_CHAT}:") for t in tokens
    )

    # No gate id: no buttons even with inbound on.
    bot.send_message.reset_mock()
    await service.notify(_request(mission, NotificationKind.GATE_TIMEOUT_PAUSED))
    assert _markup(bot, OWNER_CHAT) is None


async def test_failed_recipient_reraises_after_others_sent(
    db_session, adapter, bot, sse, monkeypatch
) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    await _add_member_recipient(db_session, mission, role="maintainer")
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    await _identity(db_session, TEST_USER_ID_2, MEMBER_CHAT)

    async def _send(**kw):
        if kw["chat_id"] == OWNER_CHAT:
            raise RuntimeError("Telegram server says - Bad Request: chat not found")
        return SimpleNamespace(message_id=7)

    bot.send_message = AsyncMock(side_effect=_send)
    service = NotificationService(db_session, event_bus=FakeBus())
    request = _request(mission, NotificationKind.RUN_FAILED)

    with pytest.raises(ExternalServiceError, match="1 notification deliveries failed"):
        await service.notify(request)
    by_user = {d.recipient_user_id: d for d in await _deliveries(db_session, mission)}
    assert by_user[TEST_USER_ID].status == NotificationDeliveryStatus.FAILED
    assert by_user[TEST_USER_ID_2].status == NotificationDeliveryStatus.SENT
    assert bot.send_message.await_count == 2

    # The retry re-attempts only the failed recipient.
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=8))
    await service.notify(request)
    assert [c.kwargs["chat_id"] for c in bot.send_message.await_args_list] == [OWNER_CHAT]
    by_user = {d.recipient_user_id: d for d in await _deliveries(db_session, mission)}
    assert by_user[TEST_USER_ID].status == NotificationDeliveryStatus.SENT
    assert by_user[TEST_USER_ID].attempt_count == 2
    assert by_user[TEST_USER_ID].error is None


async def test_delivery_error_redacts_bot_token(db_session, adapter, bot, sse, monkeypatch) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    bot.send_message = AsyncMock(
        side_effect=OSError(
            "Cannot connect to host https://api.telegram.org/bot123:ABC-def/sendMessage"
        )
    )
    bus = FakeBus()

    with pytest.raises(ExternalServiceError):
        await NotificationService(db_session, event_bus=bus).notify(
            _request(mission, NotificationKind.RUN_FAILED)
        )

    [delivery] = await _deliveries(db_session, mission)
    assert "<redacted>" in delivery.error
    assert "123:ABC-def" not in delivery.error
    [event] = bus.events
    assert event.event_type == "notification.delivery_failed"
    assert event.delivery_id == str(delivery.id)
    assert event.kind == "run_failed" and event.channel == "telegram"
    assert "<redacted>" in event.error
    assert "123:ABC-def" not in event.error


async def test_message_html_escaped_and_truncated(
    db_session, adapter, bot, sse, monkeypatch
) -> None:
    _config(monkeypatch, max_chars=500)
    mission = await _mission(db_session, name=f"<b>evil</b> & co {uuid7()}")
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    payload = {
        "sequence": 4,
        "status": "failed",
        "cost_usd": 1.5,
        "detail": "<script>" + "x" * 2000,
    }

    await NotificationService(db_session, event_bus=FakeBus()).notify(
        _request(mission, NotificationKind.RUN_FAILED, payload=payload)
    )

    text = bot.send_message.await_args.kwargs["text"]
    assert "&lt;b&gt;evil&lt;/b&gt; &amp; co" in text
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert len(text) <= 500
    assert text.endswith("…")
    assert "Run: #4" in text and "Status: failed" in text and "Cost: $1.5000" in text


async def test_publishes_sse_channel(db_session, adapter, bot, sse, monkeypatch) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    request = _request(mission, NotificationKind.RUN_SUCCEEDED, payload={"sequence": 1})

    await NotificationService(db_session, event_bus=FakeBus()).notify(request)

    [(mission_id, message)] = sse
    assert mission_id == mission.id
    assert message["kind"] == "run_succeeded"
    assert message["data"]["subject_id"] == request.subject_id
    assert mission.name in message["body"]


async def test_publish_sse_uses_mission_channel(monkeypatch) -> None:
    redis = MagicMock()
    redis.publish = AsyncMock()
    redis.aclose = AsyncMock()
    monkeypatch.setattr(notification_module.AsyncRedis, "from_url", lambda url: redis)

    await notification_module._publish_sse("m-1", {"kind": "run_failed"})

    channel, body = redis.publish.await_args.args
    assert channel == "notify:mission:m-1"
    assert '"kind": "run_failed"' in body
    redis.aclose.assert_awaited_once()


async def test_send_ad_hoc_confirmed_recipients_only_and_never_raises(
    db_session, adapter, bot, sse, monkeypatch
) -> None:
    _config(monkeypatch)
    mission = await _mission(db_session)
    await _add_member_recipient(db_session, mission, role="viewer")
    await _identity(db_session, TEST_USER_ID, OWNER_CHAT)
    await _identity(db_session, TEST_USER_ID_2, MEMBER_CHAT, verified=False)
    bot.send_message = AsyncMock(
        side_effect=OSError("https://api.telegram.org/bot123:ABC-def/sendMessage")
    )

    await NotificationService(db_session).send_ad_hoc(mission.id, "Title", "Body", "info")

    assert [c.kwargs["chat_id"] for c in bot.send_message.await_args_list] == [OWNER_CHAT]
    assert bot.send_message.await_args.kwargs["text"] == "Title\n\nBody"
    [(mission_id, message)] = sse
    assert mission_id == mission.id and message["type"] == "info"
    assert await _deliveries(db_session, mission) == []
