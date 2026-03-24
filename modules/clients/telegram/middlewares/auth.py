"""
Authentication Middleware.

User ID whitelisting and role-based access control for the Telegram bot.
Roles and user-to-role mappings are read from config/settings/security.yaml.
Telegram user IDs are immutable integers that cannot be spoofed within the Telegram API.

Authorization logic (role resolution, role comparison) is delegated to
modules.backend.core.security — this middleware is a thin enforcement layer.
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.security import check_role_level, resolve_user_role_from_config

logger = get_logger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Authentication middleware using Telegram user ID whitelisting.

    Checks if the user is in the authorized users list before processing.
    Silently drops unauthorized requests to avoid revealing bot existence.

    Configuration:
        Set authorized_users in config/settings/application.yaml.
        Set role mappings in config/settings/security.yaml under user_roles.

    Usage:
        dp.update.outer_middleware(AuthMiddleware())

        @router.message(Command("admin_command"))
        async def admin_handler(message: Message, user_role: str):
            if user_role != "admin":
                await message.answer("Unauthorized")
                return
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Process the middleware."""
        app_config = get_app_config()

        user = None
        chat_type = None

        if isinstance(event, Update):
            if event.message:
                user = event.message.from_user
                chat_type = event.message.chat.type
            elif event.callback_query:
                user = event.callback_query.from_user
                chat_type = event.callback_query.message.chat.type if event.callback_query.message else None
            elif event.inline_query:
                user = event.inline_query.from_user

        if not user:
            return await handler(event, data)

        user_id = user.id

        authorized_users = app_config.application.telegram.authorized_users

        if not authorized_users:
            logger.debug(
                "No authorized users configured, allowing all",
                extra={"user_id": user_id},
            )
            data["user_role"] = "admin"
            data["telegram_user"] = user
            return await handler(event, data)

        if user_id not in authorized_users:
            logger.warning(
                "Unauthorized Telegram access attempt",
                extra={
                    "user_id": user_id,
                    "username": user.username,
                    "chat_type": chat_type,
                },
            )
            return None

        role = resolve_user_role_from_config(user_id)

        data["user_role"] = role
        data["telegram_user"] = user

        logger.debug(
            "Authorized Telegram user",
            extra={
                "user_id": user_id,
                "username": user.username,
                "role": role,
            },
        )

        return await handler(event, data)


def require_role(min_role: str):
    """
    Decorator to require a minimum role for a handler.

    Role hierarchy is evaluated by the backend security module.

    Args:
        min_role: Minimum required role name (e.g. "viewer", "user", "admin")

    Usage:
        @router.message(Command("trade"))
        @require_role("user")
        async def trade_handler(message: Message, user_role: str):
            pass
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            user_role = kwargs.get("user_role", "viewer")

            if not check_role_level(user_role, min_role):
                message = args[0] if args else kwargs.get("message")
                if message and hasattr(message, "answer"):
                    await message.answer("⛔ You don't have permission for this action.")
                return None

            return await func(*args, **kwargs)

        return wrapper

    return decorator
