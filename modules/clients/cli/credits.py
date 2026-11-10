"""
CLI handler for --service credits.

Thin renderer over core/preflight. Checks that all models in a roster
have available credits by pinging each with a one-token call. When any
roster model is `foundry:*`, also surfaces Entra token expiry so a stale
`az login` is visible at preflight instead of mid-dispatch (Plan 82 §4.8).
"""

import asyncio
import sys
import time
from datetime import datetime, timezone


def check_credits(logger, roster: str = "default", output_format: str = "human") -> None:
    """Verify all roster models have available credits."""
    asyncio.run(_check_credits_async(logger, roster))


async def _check_foundry_token(scope: str) -> tuple[bool, str]:
    """Force an Entra token acquisition and return (ok, detail-string).

    Acquiring a token here proves the credential chain (az login locally, or
    managed identity in prod) is alive. We report the token expiry so
    operators can spot long missions that will straddle a refresh boundary.
    """
    from azure.identity.aio import DefaultAzureCredential

    cred = DefaultAzureCredential()
    try:
        token = await cred.get_token(scope)
        expires_in = token.expires_on - int(time.time())
        expires_at = datetime.fromtimestamp(token.expires_on, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        return True, f"token valid for {expires_in // 60}m (until {expires_at})"
    except Exception as exc:
        return False, f"token acquisition failed: {exc}"
    finally:
        await cred.close()


async def _check_credits_async(logger, roster: str) -> None:
    from modules.backend.agents.preflight import preflight_check
    from modules.backend.core.config import get_app_config
    from modules.clients.cli.report import build_table, get_console

    console = get_console()
    console.print(f"Preflight credit check (roster: {roster})...\n")

    try:
        result = await preflight_check(roster_name=roster)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]FAIL  {e}[/red]")
        sys.exit(1)

    table = build_table(
        "Credit Check",
        columns=[
            ("Status", {"width": 8}),
            ("Model", {"style": "cyan", "width": 44}),
            # Wrap, never truncate: the provider's message and the fix hint are at the end.
            ("Detail", {"ratio": 1, "no_wrap": False, "overflow": "fold"}),
        ],
    )

    for check in result.checks:
        if check.ok:
            table.add_row(
                "[green]PASS[/green]",
                check.model_name,
                f"{check.elapsed_ms:.0f}ms",
            )
        else:
            detail = (
                "Insufficient credits — top up at console.anthropic.com"
                if check.error_type == "insufficient_credits"
                else check.error
            )
            table.add_row("[red]FAIL[/red]", check.model_name, detail)

    console.print(table)

    # Foundry Entra token liveness — only runs when a foundry: model is in the roster.
    foundry_in_roster = any(c.model_name.startswith("foundry:") for c in result.checks)
    foundry_token_ok = True
    if foundry_in_roster:
        foundry_config = get_app_config().providers.foundry
        if foundry_config.auth_mode == "entra":
            if not foundry_config.scope:
                console.print(
                    "[red]Foundry Entra token: scope not configured in providers.yaml[/red]"
                )
                foundry_token_ok = False
            else:
                ok, detail = await _check_foundry_token(foundry_config.scope)
                colour = "green" if ok else "red"
                console.print(f"[{colour}]Foundry Entra token: {detail}[/{colour}]")
                foundry_token_ok = ok

    if result.ok and foundry_token_ok:
        console.print("[green]All models OK — ready to run executions and workflows.[/green]")
    else:
        if not result.ok:
            failed = ", ".join(c.model_name for c in result.failed)
            console.print(f"[red]Preflight failed for: {failed}[/red]")
        sys.exit(1)
