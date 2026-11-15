"""
Telegram Channel Adapter.

Wraps the existing modules/telegram/ module to conform to the
ChannelAdapter interface. The bot, dispatcher, handlers, keyboards,
and middlewares are unchanged — this adapter translates between
the gateway's standard message format and aiogram's native types.

send_notification and edit_notification (Plan 88 step 88.4.4) deliver mission
notifications: the text is HTML-escaped (the bot uses ParseMode.HTML), never
markdown-converted, and is truncated to notifications.message_max_chars.
"""

import html
import re
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.gateway.adapters import AgentResponse, ChannelAdapter

if TYPE_CHECKING:
    from aiogram import Bot

logger = get_logger(__name__)


class TelegramAdapter(ChannelAdapter):
    """
    Telegram channel adapter.

    Wraps aiogram Bot for outbound message delivery and
    provides formatting for Telegram's HTML parse mode.
    """

    def __init__(self, bot: "Bot") -> None:
        self._bot = bot

    @property
    def channel_name(self) -> str:
        return "telegram"

    @property
    def max_message_length(self) -> int:
        return get_app_config().application.telegram.max_message_length

    async def deliver_response(self, response: AgentResponse) -> bool:
        """
        Deliver a response to a Telegram chat.

        Handles chunking for messages exceeding 4096 characters.
        The session_key is the Telegram chat_id.
        """
        try:
            formatted = self.format_text(response.text)
            chunks = await self.chunk_message(formatted)

            for chunk in chunks:
                await self._bot.send_message(
                    chat_id=response.session_key,
                    text=chunk,
                    reply_to_message_id=(
                        int(response.reply_to_message_id) if response.reply_to_message_id else None
                    ),
                )

            logger.debug(
                "Telegram response delivered",
                extra={
                    "chat_id": response.session_key,
                    "chunks": len(chunks),
                    "total_length": len(response.text),
                },
            )
            return True

        except (OSError, RuntimeError, ValueError) as e:
            logger.error(
                "Failed to deliver Telegram response",
                extra={
                    "chat_id": response.session_key,
                    "error": str(e),
                },
            )
            return False

    async def send_notification(
        self, chat_id: int, text: str, actions: list[tuple[str, str]] | None
    ) -> str:
        """Send a notification to a chat; returns "{chat_id}:{message_id}".

        actions is one row of (label, callback_data) buttons. Errors from aiogram
        propagate; their text can carry the bot token, so callers redact it.
        """
        markup = None
        if actions:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text=label, callback_data=data)
                        for label, data in actions
                    ]
                ]
            )
        message = await self._bot.send_message(
            chat_id=chat_id,
            text=_notification_text(text),
            reply_markup=markup,
        )
        return f"{chat_id}:{message.message_id}"

    async def edit_notification(self, message_ref: str, text: str) -> None:
        """Replace a sent notification's text and remove its buttons."""
        chat_id, message_id = _parse_message_ref(message_ref)
        await self._bot.edit_message_text(
            text=_notification_text(text),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )

    def format_text(self, text: str) -> str:
        """
        Format text for Telegram's HTML parse mode.

        Converts standard markdown bold/italic to HTML tags.
        Telegram supports: <b>, <i>, <code>, <pre>, <a>.
        """
        result = text
        result = _convert_markdown_bold(result)
        result = _convert_markdown_italic(result)
        result = _convert_markdown_code(result)
        return result


def _notification_text(text: str) -> str:
    """HTML-escape, then truncate to notifications.message_max_chars.

    Truncation runs after escaping so the limit holds for the text Telegram
    receives; a cut never splits an entity because it backs off to the last
    complete one.
    """
    escaped = html.escape(text, quote=False)
    limit = get_app_config().notifications.message_max_chars
    if len(escaped) <= limit:
        return escaped
    cut = escaped[: limit - 1]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    return cut + "\u2026"


def _parse_message_ref(message_ref: str) -> tuple[int, int]:
    """Split "{chat_id}:{message_id}" into integers."""
    chat_id, _, message_id = message_ref.rpartition(":")
    if not chat_id or not message_id:
        raise ValueError(f"Malformed Telegram message ref: {message_ref!r}")
    return int(chat_id), int(message_id)


def _convert_markdown_bold(text: str) -> str:
    """Convert **bold** to <b>bold</b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _convert_markdown_italic(text: str) -> str:
    """Convert *italic* to <i>italic</i> (single asterisks not preceded by another)."""
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)


def _convert_markdown_code(text: str) -> str:
    """Convert `code` to <code>code</code>."""
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)
