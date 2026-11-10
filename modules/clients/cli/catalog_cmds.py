"""
CLI handler for agent catalog commands.

Thin renderer over AgentCatalogService. Handles list, detail, seeding and YAML sync.
"""

import asyncio
import json
import sys

import click

from modules.clients.cli.report import build_table, get_console


def run_catalog(
    cli_logger, action: str, *, agent_name: str | None = None, output_format: str = "human"
) -> None:
    """Dispatch catalog CLI actions."""
    actions = {
        "list": _action_list,
        "detail": _action_detail,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(fn(cli_logger, agent_name=agent_name, output_format=output_format))


def run_providers(cli_logger, *, output_format: str = "human") -> None:
    """List every LLM provider and model."""
    asyncio.run(_action_providers(cli_logger, output_format=output_format))


def run_ping(
    cli_logger,
    *,
    models: tuple[str, ...],
    providers: tuple[str, ...],
    all_models: bool,
    output_format: str = "human",
) -> None:
    """Make one live call per selected model."""
    asyncio.run(
        _action_ping(
            cli_logger,
            models=list(models),
            providers=list(providers),
            all_models=all_models,
            output_format=output_format,
        )
    )


def run_discover(cli_logger, *, provider: str, output_format: str = "human") -> None:
    """List the models a provider offers now, against the registry."""
    asyncio.run(_action_discover(cli_logger, provider=provider, output_format=output_format))


def run_sync_yaml(
    cli_logger,
    *,
    agent_name: str | None,
    dry_run: bool,
    check: bool,
    output_format: str = "human",
) -> None:
    """Write the catalog's values back into the agent YAML files."""
    asyncio.run(
        _action_sync_yaml(
            cli_logger,
            agent_name=agent_name,
            dry_run=dry_run,
            check=check,
            output_format=output_format,
        )
    )


def run_admin(
    cli_logger,
    action: str,
    *,
    force: bool = False,
    reset_prompts: bool = False,
    output_format: str = "human",
) -> None:
    """Dispatch admin CLI actions."""
    actions = {
        "seed-catalog": _action_seed_catalog,
    }
    fn = actions.get(action)
    if not fn:
        get_console().print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

    asyncio.run(
        fn(cli_logger, force=force, reset_prompts=reset_prompts, output_format=output_format)
    )


async def _action_list(cli_logger, *, output_format, **_):
    """List agents in the catalog."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    console = get_console()
    async with AgentCatalogService.factory() as svc:
        agents = await svc.list_catalog(enabled_only=False, visibility=None)

    if not agents:
        console.print("[dim]No agents in catalog. Run: cli.py admin seed-catalog[/dim]")
        return

    table = build_table(
        "Agent Catalog",
        columns=[
            ("Name", {"style": "cyan", "width": 35}),
            ("Type", {"width": 12}),
            ("Version", {"width": 10}),
            ("Enabled", {"width": 9}),
            ("Visibility", {"width": 12}),
            ("Description", {"ratio": 1}),
        ],
    )
    for a in agents:
        enabled = "[green]yes[/green]" if a.enabled else "[red]no[/red]"
        desc = a.description[:60] + "..." if len(a.description) > 60 else a.description
        table.add_row(a.agent_name, a.agent_type, a.version, enabled, a.visibility, desc)

    console.print(table)
    console.print(f"\n  [dim]{len(agents)} agents total[/dim]")


async def _action_detail(cli_logger, *, agent_name, **_):
    """Show detail for a specific agent."""
    from modules.backend.services.agent_catalog import AgentCatalogService

    console = get_console()
    if not agent_name:
        console.print("[red]AGENT_NAME is required[/red]")
        sys.exit(1)

    async with AgentCatalogService.factory() as svc:
        agent = await svc.get_by_name_or_none(agent_name)

    if not agent:
        console.print(f"[red]Agent not found: {agent_name}[/red]")
        sys.exit(1)

    console.print(f"[bold]{agent.agent_name}[/bold]  v{agent.version}")
    console.print(f"  Type:        {agent.agent_type}")
    console.print(f"  Enabled:     {agent.enabled}")
    console.print(f"  Visibility:  {agent.visibility}")
    console.print(f"  Description: {agent.description}")
    console.print(f"  Model:       {(agent.model_config_json or {}).get('name', 'N/A')}")
    console.print(f"  Tools:       {', '.join(agent.tools or []) or 'none'}")
    console.print(f"  Keywords:    {', '.join(agent.keywords or []) or 'none'}")

    if agent.system_prompt:
        prompt_preview = agent.system_prompt[:200]
        if len(agent.system_prompt) > 200:
            prompt_preview += "..."
        console.print(f"\n  [bold]System Prompt[/bold] ({len(agent.system_prompt)} chars):")
        console.print(f"    {prompt_preview}")


async def _action_seed_catalog(cli_logger, *, force, reset_prompts=False, **_):
    """Seed the agent catalog from YAML config files via the admin API.

    Routed through the API so the backend's in-memory registry is
    invalidated atomically with the catalog write — a direct DB write
    here would leave the running backend serving stale model bindings.
    """
    from urllib.parse import urlencode

    from modules.clients.cli.api_client import api_client

    console = get_console()
    query = urlencode({"force": str(force).lower(), "reset_prompts": str(reset_prompts).lower()})
    async with api_client() as api:
        counts = await api.post(f"/admin/seed-catalog?{query}")

    console.print("[bold]Catalog seeding complete[/bold]")
    console.print(f"  Seeded:  {counts['seeded']}")
    console.print(f"  Skipped: {counts['skipped']}")
    console.print(f"  Errors:  {counts['errors']}")


async def _action_providers(cli_logger, *, output_format, **_):
    """List every LLM provider with its auth state and models."""
    from modules.backend.services.model_provider import ModelProviderService

    async with ModelProviderService.factory() as svc:
        listing = await svc.list_providers()

    if output_format == "json":
        click.echo(listing.model_dump_json(indent=2))
        return

    console = get_console()
    colours = {"present": "green", "missing": "red", "not_checked": "yellow"}

    providers = build_table(
        "Providers",
        columns=[
            ("Provider", {"style": "cyan"}),
            ("Auth mode", {}),
            ("Credential", {}),
            ("Env var", {"style": "dim"}),
            ("Base URL", {"ratio": 1, "style": "dim"}),
        ],
    )
    for p in listing.providers:
        colour = colours[p.credential]
        providers.add_row(
            p.provider,
            p.auth_mode or "-",
            f"[{colour}]{p.credential}[/{colour}]",
            p.credential_env_var or "-",
            p.base_url or "-",
        )
    console.print(providers)

    models = build_table(
        "Models",
        columns=[
            ("Model", {"style": "cyan"}),
            ("Registered", {}),
            ("Agents", {"justify": "right"}),
            ("Aliases", {}),
        ],
    )
    for p in listing.providers:
        for m in p.models:
            registered = "[green]yes[/green]" if m.registered else "[red]no[/red]"
            models.add_row(m.qualified_name, registered, str(len(m.agents)), ", ".join(m.aliases))
    console.print(models)

    if listing.agents_without_model:
        console.print(
            "[red]Agents with no model name:[/red] " + ", ".join(listing.agents_without_model)
        )
    console.print(
        "[dim]not_checked = no static credential to read (Entra, Copilot sign-in); "
        "run 'catalog ping' to prove it.[/dim]"
    )


async def _action_ping(cli_logger, *, models, providers, all_models, output_format, **_):
    """Make one live call per selected model; exit 1 if any fails."""
    from modules.backend.core.exceptions import ValidationError
    from modules.backend.core.model_providers import close_foundry_credentials
    from modules.backend.services.model_provider import ModelProviderService

    console = get_console()
    try:
        async with ModelProviderService.factory() as svc:
            report = await svc.ping(models=models, providers=providers, all_models=all_models)
    except ValidationError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    finally:
        # This process makes no further LLM calls; release the shared Entra session.
        await close_foundry_credentials()

    if output_format == "json":
        click.echo(report.model_dump_json(indent=2))
    else:
        table = build_table(
            "Model Ping",
            columns=[
                ("Status", {"width": 8}),
                ("Model", {"style": "cyan"}),
                ("Latency", {"justify": "right"}),
                # Wrap, never truncate: the provider's message and the fix hint are at the end.
                ("Detail", {"ratio": 1, "no_wrap": False, "overflow": "fold"}),
            ],
        )
        for r in report.results:
            status = "[green]PASS[/green]" if r.ok else "[red]FAIL[/red]"
            table.add_row(status, r.model, f"{r.elapsed_ms:.0f}ms", r.error or "")
        console.print(table)

    if not report.ok:
        sys.exit(1)


async def _action_discover(cli_logger, *, provider, output_format, **_):
    """List the models a provider offers now; exit 1 if the registry is wrong about one."""
    from modules.backend.core.exceptions import ApplicationError
    from modules.backend.core.model_providers import close_foundry_credentials
    from modules.backend.services.model_provider import ModelProviderService

    console = get_console()
    try:
        async with ModelProviderService.factory() as svc:
            discovery = await svc.discover(provider)
    except ApplicationError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    finally:
        # This process makes no further Azure calls; release the shared Entra session.
        await close_foundry_credentials()

    if output_format == "json":
        click.echo(discovery.model_dump_json(indent=2))
    else:
        table = build_table(
            f"{provider} models",
            columns=[
                ("Name", {"style": "cyan"}),
                ("Model", {}),
                ("Format", {}),
                ("Version", {"style": "dim"}),
                ("Created", {"style": "dim"}),
                ("SKU", {"style": "dim"}),
                ("State", {}),
                ("Registered", {}),
                ("Agents", {"justify": "right"}),
            ],
        )
        for m in discovery.models:
            if m.state is None:
                state = "-"
            else:
                colour = "green" if m.state == "Succeeded" else "red"
                state = f"[{colour}]{m.state}[/{colour}]"
            registered = "[green]yes[/green]" if m.registered else "[yellow]no[/yellow]"
            table.add_row(
                m.name,
                m.model,
                m.format,
                m.version or "-",
                m.created or "-",
                m.sku or "-",
                state,
                registered,
                str(len(m.agents)),
            )
        console.print(table)

        for gone in discovery.not_deployed:
            users = ", ".join(gone.agents) or "no agents"
            console.print(f"[red]In the registry but not deployed:[/red] {gone.name} ({users})")
        for wrong in discovery.protocol_mismatches:
            users = ", ".join(wrong.agents) or "no agents"
            console.print(
                f"[red]Registered under {wrong.registered}, but the deployment speaks "
                f"{wrong.expected}:[/red] {wrong.name} ({users})"
            )
        if discovery.unmapped_formats:
            console.print(
                f"[yellow]Not checked against a protocol:[/yellow] deployment format(s) "
                f"{', '.join(discovery.unmapped_formats)} have no entry in "
                f"providers.yaml {provider}.deployment_protocols."
            )
        console.print(
            "[dim]Registered = listed in config/settings/models.yaml. "
            "Add a deployment there before agents or 'catalog ping' can use it.[/dim]"
        )

    if discovery.not_deployed or discovery.protocol_mismatches:
        sys.exit(1)


def _shown(value) -> str:
    """A compact one-line rendering of a YAML or database value."""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 48 else text[:45] + "..."


async def _action_sync_yaml(cli_logger, *, agent_name, dry_run, check, output_format, **_):
    """Write the catalog's values into the agent YAML files; --check exits 1 on drift."""
    from modules.backend.core.exceptions import ValidationError
    from modules.backend.services.catalog_yaml_sync import CatalogYamlSyncService

    console = get_console()
    try:
        async with CatalogYamlSyncService.factory() as svc:
            plan = await svc.plan(agent_name=agent_name)
    except ValidationError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    report = plan.report
    writes = not (dry_run or check)
    if writes:
        CatalogYamlSyncService.apply(plan)

    if output_format == "json":
        click.echo(report.model_dump_json(indent=2))
    else:
        if report.drifted:
            table = build_table(
                "Agent YAML differs from the catalog",
                columns=[
                    ("Agent", {"style": "cyan"}),
                    ("Field", {}),
                    ("YAML", {"style": "dim"}),
                    ("Catalog", {}),
                ],
            )
            for drift in report.drifted:
                for change in drift.changes:
                    table.add_row(
                        drift.agent_name,
                        change.field,
                        _shown(change.yaml_value),
                        _shown(change.database_value),
                    )
            console.print(table)

        for failure in report.failures:
            console.print(
                f"[red]Not synced:[/red] {failure.agent_name} ({failure.path}): {failure.reason}"
            )
        for name in report.database_only:
            console.print(f"[dim]In the catalog with no YAML file: {name}[/dim]")
        for name in report.yaml_only:
            console.print(f"[dim]YAML file not in the catalog yet: {name}[/dim]")

        files = len(plan.writes)
        if writes:
            summary = f"Updated {files} file(s)"
        else:
            summary = f"{files} file(s) would be updated"
        console.print(f"{summary}; {report.in_sync} agent(s) already in sync.")

    if (check and not report.clean) or (writes and report.failures):
        sys.exit(1)
