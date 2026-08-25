"""Admin CLI — Agent Catalog commands (Plan 84 Phase 5.5, split out of root admin.py).

Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Agent Catalog commands
# =============================================================================


@click.group("catalog", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def catalog(ctx):
    """Browse and manage the agent catalog.

    \b
    Examples:
        python admin.py catalog list
        python admin.py catalog detail vertical.software.quality.agent
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@catalog.command("list")
@click.pass_obj
def catalog_list(ctx):
    """List all agents in the catalog."""
    from modules.clients.cli.catalog_cmds import run_catalog

    run_catalog(ctx.logger, "list", output_format=ctx.output_format)


@catalog.command("detail")
@click.argument("agent_name")
@click.pass_obj
def catalog_detail(ctx, agent_name):
    """Show detail for a specific agent."""
    from modules.clients.cli.catalog_cmds import run_catalog

    run_catalog(ctx.logger, "detail", agent_name=agent_name, output_format=ctx.output_format)


@catalog.command("models")
@click.pass_obj
def catalog_models(ctx):
    """List all agents with their current model provider and name.

    \b
    Examples:
        python admin.py catalog models
    """
    import asyncio

    from modules.clients.common.display import build_table, get_console

    async def _run():
        from sqlalchemy import text

        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            result = await db.execute(text("""
                SELECT agent_name, model_config_json->>'name' as model, enabled
                FROM agent_catalog
                ORDER BY agent_name
            """))
            rows = list(result)

        console = get_console()
        table = build_table(
            "Agent Models",
            columns=[
                ("Agent", {"style": "cyan"}),
                ("Model", {"style": "green"}),
                ("Provider", {"style": "yellow"}),
                ("Enabled", {"style": "dim"}),
            ],
        )

        for row in rows:
            model = row[1] or "N/A"
            provider = model.split(":")[0] if ":" in model else "unknown"
            enabled = "yes" if row[2] else "no"
            style = None if row[2] else "dim"
            table.add_row(row[0], model, provider, enabled, style=style)

        console.print(table)

    asyncio.run(_run())


@catalog.command("set-model")
@click.argument("agent_name")
@click.argument("model")
@click.pass_obj
def catalog_set_model(ctx, agent_name, model):
    """Change the model for a specific agent.

    \b
    Examples:
        python admin.py catalog set-model mission.planning.agent copilot:claude-haiku-4.5
        python admin.py catalog set-model research.strategist.agent copilot:claude-sonnet-4.6
    """
    import asyncio

    async def _run():
        from modules.clients.cli.api_client import api_client

        async with api_client() as api:
            entry = await api.get(f"/catalog/agents/{agent_name}")
            old_config = entry.get("model_config_json") or {}
            old_model = old_config.get("name", "N/A")
            new_config = dict(old_config)
            new_config["name"] = model
            await api.patch(
                f"/admin/catalog/{agent_name}",
                body={"model_config_json": new_config},
            )
            click.echo(f"{agent_name}: {old_model} -> {model}")

    asyncio.run(_run())


@catalog.command("set-provider")
@click.argument("provider", type=click.Choice(["copilot", "anthropic"]))
@click.option(
    "--model-map",
    type=str,
    default=None,
    help="Comma-separated old=new model mappings, e.g. 'haiku-4-5=claude-haiku-4.5,sonnet-4-6=claude-sonnet-4.6'",  # noqa: E501
)
@click.option("--dry-run", is_flag=True, help="Show changes without applying them")
@click.pass_obj
def catalog_set_provider(ctx, provider, model_map, dry_run):
    """Switch all agents to a provider (copilot or anthropic).

    Rewrites the provider prefix on every agent's model name. Model names
    are mapped between provider naming conventions automatically:

    \b
      anthropic:claude-haiku-4-5       <-> copilot:claude-haiku-4.5
      anthropic:claude-sonnet-4-6      <-> copilot:claude-sonnet-4.6
      anthropic:claude-opus-4-6        <-> copilot:claude-opus-4.6

    \b
    Examples:
        python admin.py catalog set-provider copilot
        python admin.py catalog set-provider anthropic
        python admin.py catalog set-provider copilot --dry-run
    """
    import asyncio

    # Default model name mappings between providers
    TO_COPILOT = {
        "claude-haiku-4-5": "claude-haiku-4.5",
        "claude-haiku-4-5-20251001": "claude-haiku-4.5",
        "claude-sonnet-4-6": "claude-sonnet-4.6",
        "claude-sonnet-4-5-20241022": "claude-sonnet-4.6",
        "claude-opus-4-6": "claude-opus-4.6",
    }
    TO_ANTHROPIC = {
        v: k for k, v in TO_COPILOT.items() if "20251001" not in k and "20241022" not in k
    }

    mapping = TO_COPILOT if provider == "copilot" else TO_ANTHROPIC

    # Parse user overrides
    if model_map:
        for pair in model_map.split(","):
            old, new = pair.strip().split("=")
            mapping[old.strip()] = new.strip()

    async def _run():
        from modules.clients.cli.api_client import api_client

        async with api_client() as api:
            listing = await api.get("/admin/catalog", params={"enabled_only": False})
            entries = listing.get("agents", [])

            changed = 0
            for entry in entries:
                config = entry.get("model_config_json") or {}
                current = config.get("name", "")
                if not current:
                    continue

                # Already on this provider
                if current.startswith(f"{provider}:"):
                    continue

                # Extract model name from current provider
                parts = current.split(":", 1)
                old_model = parts[1] if len(parts) > 1 else current

                # Map model name
                new_model = mapping.get(old_model, old_model)
                new_full = f"{provider}:{new_model}"

                if dry_run:
                    click.echo(f"  {entry['agent_name']}: {current} -> {new_full}")
                else:
                    new_config = dict(config)
                    new_config["name"] = new_full
                    await api.patch(
                        f"/admin/catalog/{entry['agent_name']}",
                        body={"model_config_json": new_config},
                    )
                    click.echo(f"  {entry['agent_name']}: {current} -> {new_full}")

                changed += 1

            label = "Would change" if dry_run else "Changed"
            click.echo(f"\n{label} {changed} agent(s)")

    asyncio.run(_run())


@catalog.group("aliases", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def catalog_aliases(ctx):
    """Manage model aliases (quick / moderate / comprehensive).

    \b
    Examples:
        python admin.py catalog aliases list
        python admin.py catalog aliases set quick copilot:claude-haiku-4.5
        python admin.py catalog aliases set moderate anthropic:claude-sonnet-4-6
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@catalog_aliases.command("list")
@click.pass_obj
def catalog_aliases_list(ctx):
    """List all model aliases from models.yaml."""
    from modules.backend.core.config import get_app_config
    from modules.clients.common.display import build_table, get_console

    aliases = get_app_config().models.aliases
    table = build_table(
        "Model Aliases",
        columns=[
            ("Alias", {"style": "cyan"}),
            ("Resolves To", {"style": "green"}),
            ("Provider", {"style": "yellow"}),
        ],
    )

    for alias, full_name in sorted(aliases.items()):
        provider = full_name.split(":")[0] if ":" in full_name else "unknown"
        table.add_row(alias, full_name, provider)

    get_console().print(table)


@catalog_aliases.command("set")
@click.argument("alias")
@click.argument("model")
@click.pass_obj
def catalog_aliases_set(ctx, alias, model):
    """Set a model alias in models.yaml.

    \b
    Examples:
        python admin.py catalog aliases set quick copilot:claude-haiku-4.5
        python admin.py catalog aliases set comprehensive anthropic:claude-opus-4-6
    """
    import re

    import yaml

    from modules.backend.core.config import find_project_root

    if ":" not in model:
        click.echo(
            f"Error: model must be a fully-qualified 'provider:model' string, got '{model}'",
            err=True,
        )
        raise SystemExit(1)

    models_path = find_project_root() / "config" / "settings" / "models.yaml"
    text = models_path.read_text()
    raw = yaml.safe_load(text) or {}

    old = (raw.get("aliases") or {}).get(alias, "(new)")

    # Patch in-place to preserve comments. Replace existing alias line or append under aliases:.
    line_pattern = re.compile(rf"^(\s+){re.escape(alias)}:.*$", re.MULTILINE)
    new_line = f'  {alias}: "{model}"'
    if line_pattern.search(text):
        text = line_pattern.sub(new_line, text)
    else:
        text = text.rstrip("\n") + f"\n{new_line}\n"

    models_path.write_text(text)

    click.echo(f"aliases.{alias}: {old} -> {model}")
    click.echo(f"Written to {models_path}")
    click.echo(
        "Note: restart the backend service to pick up the change (config is cached at startup)."
    )
