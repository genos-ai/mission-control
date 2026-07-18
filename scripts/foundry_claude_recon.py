"""Foundry Claude recon — discover deployed Claude models in the current Azure subscription.

Walks every Cognitive Services / Foundry account visible to the active Entra
identity, lists each account's model deployments, and reports any Anthropic /
Claude deployments — with the exact endpoint URL and deployment name needed
to wire a `foundry-anthropic:` provider (or extend `foundry:` to reach them).

Why this is a one-shot script and not an admin subcommand: this is recon, not
an operator workflow. Run it once to discover what's available, then encode
the result in providers.yaml.

Usage:
    az login                                 # if needed
    az account set --subscription <name>     # to change subscription
    python scripts/foundry_claude_recon.py --verbose
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

# Make modules.* imports work when invoked directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import click  # noqa: E402

from modules.backend.core.logging import get_logger  # noqa: E402
from modules.clients.cli.report import build_table, get_console  # noqa: E402

logger = get_logger(__name__)


CLAUDE_MARKERS = ("claude", "anthropic")


def _az(args: list[str]) -> str:
    """Run `az <args>` returning stdout. Raises on non-zero exit."""
    logger.debug("az %s", " ".join(args))
    result = subprocess.run(
        ["az", *args, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`az {' '.join(args)}` failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def current_subscription() -> dict:
    return json.loads(_az(["account", "show"]))


def list_accounts() -> list[dict]:
    """All CognitiveServices accounts (AIServices / OpenAI / etc.) in the current subscription."""
    return json.loads(_az(["cognitiveservices", "account", "list"]))


def list_deployments(account_name: str, resource_group: str) -> list[dict]:
    """Model deployments under one CognitiveServices account."""
    return json.loads(
        _az(
            [
                "cognitiveservices",
                "account",
                "deployment",
                "list",
                "--name",
                account_name,
                "--resource-group",
                resource_group,
            ]
        )
    )


def is_claude_deployment(deployment: dict) -> bool:
    """A deployment is Claude if its model.format or model.name names Anthropic/Claude."""
    model = deployment.get("properties", {}).get("model", {}) or {}
    fmt = (model.get("format") or "").lower()
    name = (model.get("name") or "").lower()
    return any(m in fmt for m in CLAUDE_MARKERS) or any(m in name for m in CLAUDE_MARKERS)


def main_logic() -> tuple[dict, list[dict], list[dict]]:
    """Return (subscription_info, claude_rows, aiservices_candidates)."""
    sub = current_subscription()
    logger.info(
        "Subscription: %s (%s) tenant=%s user=%s",
        sub.get("name"),
        sub.get("id"),
        sub.get("tenantId"),
        sub.get("user", {}).get("name"),
    )

    accounts = list_accounts()
    logger.info("Found %d CognitiveServices accounts", len(accounts))

    claude_rows: list[dict] = []
    aiservices_candidates: list[dict] = []
    for acc in accounts:
        acc_name = acc["name"]
        rg = acc["resourceGroup"]
        kind = acc.get("kind", "")
        endpoint = acc.get("properties", {}).get("endpoint", "")
        location = acc.get("location", "")
        logger.debug("Account %s (kind=%s, rg=%s)", acc_name, kind, rg)

        # AIServices is the kind that can host Anthropic/Claude. OpenAI-kind
        # resources can only host Azure OpenAI models.
        if kind == "AIServices":
            aiservices_candidates.append(
                {
                    "account": acc_name,
                    "resource_group": rg,
                    "location": location,
                    "endpoint": endpoint,
                }
            )

        try:
            deployments = list_deployments(acc_name, rg)
        except RuntimeError as exc:
            logger.warning("Skip %s — deployment list failed: %s", acc_name, exc)
            continue

        for dep in deployments:
            if not is_claude_deployment(dep):
                continue
            model = dep["properties"]["model"]
            claude_rows.append(
                {
                    "account": acc_name,
                    "kind": kind,
                    "location": location,
                    "endpoint": endpoint,
                    "deployment": dep["name"],
                    "model_format": model.get("format", ""),
                    "model_name": model.get("name", ""),
                    "model_version": model.get("version", ""),
                    "sku": dep.get("sku", {}).get("name", ""),
                }
            )

    return sub, claude_rows, aiservices_candidates


def render(sub: dict, rows: list[dict], candidates: list[dict]) -> None:
    console = get_console()
    console.print(f"[bold]Subscription:[/bold] {sub.get('name')} " f"([dim]{sub.get('id')}[/dim])")
    console.print(f"[bold]Identity:[/bold] {sub.get('user', {}).get('name')}\n")

    if not rows:
        console.print(
            "[yellow]No Claude / Anthropic deployments found in this subscription.[/yellow]\n"
        )
        if candidates:
            cand_table = build_table(
                "AIServices accounts that could host a Claude deployment",
                columns=[
                    ("Account", {"style": "cyan", "width": 36}),
                    ("Resource Group", {"width": 36}),
                    ("Location", {"width": 14}),
                    ("Endpoint", {"ratio": 1}),
                ],
            )
            for c in candidates:
                cand_table.add_row(
                    c["account"],
                    c["resource_group"],
                    c["location"] or "—",
                    c["endpoint"] or "—",
                )
            console.print(cand_table)
        console.print(
            "\nNext steps:"
            "\n  • To deploy: ai.azure.com → Models + endpoints → Deploy model → Anthropic → claude-opus-4-7 (or sonnet/haiku)."
            "\n  • To search other subscriptions: `az account set --subscription <name>` then re-run."
        )
        return

    table = build_table(
        "Claude / Anthropic deployments",
        columns=[
            ("Account", {"style": "cyan", "width": 32}),
            ("Deployment", {"style": "green", "width": 28}),
            ("Model", {"style": "yellow", "width": 22}),
            ("Version", {"width": 14}),
            ("Endpoint", {"ratio": 1}),
        ],
    )
    for r in rows:
        table.add_row(
            r["account"],
            r["deployment"],
            r["model_name"],
            r["model_version"] or "—",
            r["endpoint"] or "—",
        )
    console.print(table)

    console.print("\n[bold]Wiring hints:[/bold]")
    for r in rows:
        endpoint = (r["endpoint"] or "").rstrip("/")
        console.print(
            f"  • [green]{r['model_name']}[/green] → "
            f"base_url = [cyan]{endpoint}[/cyan], "
            f"deployment = [yellow]{r['deployment']}[/yellow] "
            f"(kind=[dim]{r['kind']}[/dim], sku=[dim]{r['sku'] or '—'}[/dim])"
        )


@click.command()
@click.option("--verbose", is_flag=True, help="INFO-level logging.")
@click.option("--debug", is_flag=True, help="DEBUG-level logging.")
def main(verbose: bool, debug: bool) -> None:
    """Discover deployed Claude models in the active Azure subscription."""
    level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s — %(message)s")

    try:
        sub, rows, candidates = main_logic()
    except RuntimeError as exc:
        get_console().print(f"[red]FAIL[/red] {exc}")
        sys.exit(1)

    render(sub, rows, candidates)
    sys.exit(0 if rows else 2)  # exit 2 = "no Claude found" so CI can branch on it


if __name__ == "__main__":
    main()
