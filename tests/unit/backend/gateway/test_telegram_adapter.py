"""TelegramAdapter notification delivery (Plan 88 step 88.4.4)."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.backend.gateway.adapters.telegram import TelegramAdapter
from modules.backend.services.action_token import TOKEN_BYTES


@pytest.fixture
def bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=42))
    bot.edit_message_text = AsyncMock()
    return bot


async def test_send_notification_returns_chat_message_ref(bot) -> None:
    ref = await TelegramAdapter(bot=bot).send_notification(-100123, "a < b & c", None)

    assert ref == "-100123:42"
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    assert kwargs["text"] == "a &lt; b &amp; c"
    assert kwargs["reply_markup"] is None


async def test_callback_data_under_64_bytes(bot) -> None:
    # The longest raw token ActionTokenService issues: 16 bytes, base64url, no padding.
    token = base64.urlsafe_b64encode(b"\xff" * TOKEN_BYTES).rstrip(b"=").decode()
    actions = [("Approve", f"g:{token}:a"), ("Reject", f"g:{token}:r")]

    await TelegramAdapter(bot=bot).send_notification(1, "gate", actions)

    [row] = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
    assert [b.text for b in row] == ["Approve", "Reject"]
    assert len(token) == 22
    assert all(len(b.callback_data.encode()) <= 64 for b in row)


async def test_edit_notification_removes_keyboard(bot) -> None:
    await TelegramAdapter(bot=bot).edit_notification("-100123:42", "Approved <by> owner")

    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    assert kwargs["message_id"] == 42
    assert kwargs["text"] == "Approved &lt;by&gt; owner"
    assert kwargs["reply_markup"] is None
