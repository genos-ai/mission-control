"""
Unit tests for the Telegram webhook router (Plan 88 step 88.0.14).

The webhook secret is mandatory: the router refuses to build without it, and
every request without a matching X-Telegram-Bot-Api-Secret-Token header gets
403 before the body is parsed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.clients.telegram.webhook import get_webhook_router

WEBHOOK_PATH = "/webhook/telegram"
SECRET = "s" * 32
HEADER = "X-Telegram-Bot-Api-Secret-Token"
UPDATE_BODY = {
    "update_id": 42,
    "message": {
        "message_id": 1,
        "date": 1700000000,
        "chat": {"id": 123456789, "type": "private"},
        "from": {"id": 123456789, "is_bot": False, "first_name": "Op"},
        "text": "/start",
    },
}


def _patch_config(secret: str):
    settings = MagicMock()
    settings.telegram_webhook_secret = secret
    app_config = MagicMock()
    app_config.application.telegram.webhook_path = WEBHOOK_PATH
    return (
        patch("modules.clients.telegram.webhook.get_settings", return_value=settings),
        patch("modules.clients.telegram.webhook.get_app_config", return_value=app_config),
    )


@pytest.fixture
def dp() -> MagicMock:
    dispatcher = MagicMock()
    dispatcher.feed_update = AsyncMock()
    return dispatcher


@pytest.fixture
def client(dp: MagicMock) -> TestClient:
    settings_patch, config_patch = _patch_config(SECRET)
    with settings_patch, config_patch:
        router = get_webhook_router(MagicMock(), dp)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_webhook_without_secret_config_refuses_start(dp: MagicMock) -> None:
    settings_patch, config_patch = _patch_config("")
    with settings_patch, config_patch, pytest.raises(RuntimeError):
        get_webhook_router(MagicMock(), dp)


def test_webhook_missing_header_403(client: TestClient, dp: MagicMock) -> None:
    response = client.post(WEBHOOK_PATH, json=UPDATE_BODY)

    assert response.status_code == 403
    dp.feed_update.assert_not_awaited()


def test_webhook_wrong_header_403(client: TestClient, dp: MagicMock) -> None:
    response = client.post(WEBHOOK_PATH, json=UPDATE_BODY, headers={HEADER: "wrong"})

    assert response.status_code == 403
    dp.feed_update.assert_not_awaited()


def test_webhook_valid_header_accepted(client: TestClient, dp: MagicMock) -> None:
    response = client.post(WEBHOOK_PATH, json=UPDATE_BODY, headers={HEADER: SECRET})

    assert response.status_code == 200
    dp.feed_update.assert_awaited_once()
    update = dp.feed_update.await_args.args[1]
    assert update.update_id == 42
