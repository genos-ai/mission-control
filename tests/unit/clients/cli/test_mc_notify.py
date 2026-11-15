"""`mc notify recipients` (Plan 88 step 88.4.4, contracts 3.5.4): thin client over the API."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from modules.clients.cli.mc_groups.notify import notify

MISSION_ID = "22222222-2222-2222-2222-222222222222"
RECIPIENT_ID = "55555555-5555-5555-5555-555555555555"
PATH = f"/missions/{MISSION_ID}/notification-recipients"
ALICE = {
    "id": RECIPIENT_ID,
    "user_id": "66666666-6666-6666-6666-666666666666",
    "user_email": "alice@example.com",
    "channel": "telegram",
    "kinds": ["run_failed"],
}


class FakeApi:
    """Answers GET with `listing`; records every call."""

    def __init__(self, listing: list[dict[str, Any]] | None = None, reply: Any = None):
        self.listing = listing or []
        self.reply = reply if reply is not None else {}
        self.calls: list[tuple[str, str, Any]] = []

    async def get_current_mission_id(self) -> str:
        return MISSION_ID

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, params))
        return {"recipients": self.listing}

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append(("POST", path, body))
        return self.reply

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("DELETE", path, params))
        return {"id": path.rsplit("/", 1)[-1]}


def _invoke(api: FakeApi, args: list[str]):
    @asynccontextmanager
    async def _client():
        yield api

    with patch("modules.clients.cli.mc_groups.notify.api_client", _client):
        return CliRunner().invoke(notify, ["recipients", *args])


def test_recipients_add_calls_endpoint():
    api = FakeApi(reply=ALICE)

    result = _invoke(
        api,
        ["add", "alice@example.com", "--kind", "run_failed", "--kind", "gate_waiting"],
    )

    assert result.exit_code == 0, result.output
    assert api.calls == [
        (
            "POST",
            PATH,
            {
                "user_email": "alice@example.com",
                "channel": "telegram",
                "kinds": ["run_failed", "gate_waiting"],
            },
        )
    ]
    assert "alice@example.com" in result.output


def test_recipients_add_without_kind_sends_no_kinds():
    api = FakeApi(reply=ALICE)

    result = _invoke(api, ["add", "alice@example.com"])

    assert result.exit_code == 0, result.output
    assert api.calls[-1][2] == {
        "user_email": "alice@example.com",
        "channel": "telegram",
    }


def test_recipients_remove_resolves_id_by_email():
    api = FakeApi(listing=[ALICE])

    result = _invoke(api, ["remove", "alice@example.com"])

    assert result.exit_code == 0, result.output
    assert api.calls[-1] == ("DELETE", f"{PATH}/{RECIPIENT_ID}", None)


def test_recipients_remove_unknown_email_exits_1():
    api = FakeApi(listing=[ALICE])

    result = _invoke(api, ["remove", "bob@example.com"])

    assert result.exit_code == 1
    assert not [c for c in api.calls if c[0] == "DELETE"]


def test_recipients_list_renders():
    api = FakeApi(listing=[ALICE])

    result = _invoke(api, ["list"])

    assert result.exit_code == 0, result.output
    assert api.calls == [("GET", PATH, None)]
