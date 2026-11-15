"""Mission notification CLI renderer (Plan 88 step 88.4.4, contracts 3.5.4).

`mc notify recipients` manages who receives the current mission's
notifications, through the REST API only. A recipient is addressed by the
user's email; `remove` finds the recipient id by email in the list response.
Kinds are lowercase NotificationKind values. Zero backend-service imports.
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

from modules.clients.cli.api_client import CliApiClient
from modules.clients.cli.report import build_table, get_console

CHANNEL_TELEGRAM = "telegram"


def _path(mission_id: str) -> str:
    return f"/missions/{mission_id}/notification-recipients"


async def list_recipients(api: CliApiClient, *, mission_id: str, as_json: bool) -> None:
    """Print the mission's notification recipients."""
    data = await api.get(_path(mission_id))
    recipients = data.get("recipients", []) if isinstance(data, dict) else []
    console = get_console()
    if as_json:
        console.print(json.dumps(data, indent=2, default=str))
        return
    if not recipients:
        console.print("[dim]No recipients. Add one with `mc notify recipients add EMAIL`.[/dim]")
        return
    table = build_table(
        "Notification Recipients",
        columns=[
            ("Email", {"style": "cyan", "width": 32}),
            ("Channel", {"width": 10}),
            ("Kinds", {}),
        ],
    )
    for r in recipients:
        table.add_row(r.get("user_email", ""), r.get("channel", ""), ", ".join(r.get("kinds", [])))
    console.print(table)


async def add_recipient(
    api: CliApiClient, *, mission_id: str, email: str, kinds: tuple[str, ...]
) -> None:
    """Subscribe a mission owner or member on Telegram; no --kind means the default kinds."""
    body: dict[str, Any] = {"user_email": email, "channel": CHANNEL_TELEGRAM}
    if kinds:
        body["kinds"] = list(kinds)
    r = await api.post(_path(mission_id), body=body)
    get_console().print(
        f"[green]Recipient added:[/green] [cyan]{r.get('user_email')}[/cyan]  "
        f"channel={r.get('channel')}  kinds={', '.join(r.get('kinds', []))}"
    )


async def remove_recipient(api: CliApiClient, *, mission_id: str, email: str) -> None:
    """Remove the recipient whose email matches exactly."""
    data = await api.get(_path(mission_id))
    for r in data.get("recipients", []) if isinstance(data, dict) else []:
        if r.get("user_email") == email:
            await api.delete(f"{_path(mission_id)}/{r['id']}")
            get_console().print(f"[green]Recipient removed:[/green] [cyan]{email}[/cyan]")
            return
    _fail(f"No recipient with email '{email}'")


def _fail(message: str) -> NoReturn:
    get_console().print(f"[red]{message}[/red]")
    sys.exit(1)
