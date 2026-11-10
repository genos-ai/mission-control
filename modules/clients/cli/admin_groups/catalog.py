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


@catalog.command("providers")
@click.pass_obj
def catalog_providers(ctx):
    """List every LLM provider: auth state, models, and which agents use them.

    \b
    Examples:
        python admin.py catalog providers
        python admin.py --output json catalog providers
    """
    from modules.clients.cli.catalog_cmds import run_providers

    run_providers(ctx.logger, output_format=ctx.output_format)


@catalog.command("ping")
@click.option("--model", "models", multiple=True, help="provider:model or alias. Repeatable.")
@click.option("--provider", "providers", multiple=True, help="Every model of a provider.")
@click.option("--all", "all_models", is_flag=True, help="Every model in the registry.")
@click.pass_obj
def catalog_ping(ctx, models, providers, all_models):
    """Make one live call per model to prove provider, auth and model work.

    The call asks for structured output in the model's registry output_mode, so
    a model that rejects a forced tool choice under 'tool' mode fails here.
    Select with --model, --provider or --all. Models must be in the registry.
    Exits 1 if any call fails.

    \b
    Examples:
        python admin.py catalog ping --model quick
        python admin.py catalog ping --provider foundry
        python admin.py catalog ping --all
    """
    from modules.clients.cli.catalog_cmds import run_ping

    run_ping(
        ctx.logger,
        models=models,
        providers=providers,
        all_models=all_models,
        output_format=ctx.output_format,
    )


@catalog.command("discover")
@click.option(
    "--provider",
    required=True,
    help="Provider to query; an unsupported one lists the supported providers.",
)
@click.pass_obj
def catalog_discover(ctx, provider):
    """List the models a provider offers now, against the model registry.

    Shows each deployment, whether it is in the registry, and how many agents
    use it. Exits 1 if the registry names a model the provider does not offer, or
    files one under a protocol its deployment cannot speak.
    Foundry needs 'az login' and Reader access to the Azure resource; Anthropic
    needs its API key. Anthropic lists dated snapshot ids; a registry name matches
    the id or its undated alias.

    \b
    Examples:
        python admin.py catalog discover --provider foundry
        python admin.py catalog discover --provider anthropic
        python admin.py --output json catalog discover --provider foundry
    """
    from modules.clients.cli.catalog_cmds import run_discover

    run_discover(ctx.logger, provider=provider, output_format=ctx.output_format)


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


@catalog.command("sync-yaml")
@click.option("--agent", "agent_name", default=None, help="Only this agent (default: all).")
@click.option("--dry-run", is_flag=True, help="Show the changes without writing any file.")
@click.option(
    "--check",
    is_flag=True,
    help="Write nothing; exit 1 if any agent YAML differs from the catalog (for CI).",
)
@click.pass_obj
def catalog_sync_yaml(ctx, agent_name, dry_run, check):
    """Write the catalog's values back into the agent YAML files.

    The database is the source of truth; config/agents/**/agent.yaml seeds it.
    After a runtime change (the admin API, set-provider, set-model) the YAML is
    stale, and 'seed-catalog --force' would revert the change. This edits the
    existing files in place, keeping comments and formatting.

    Synced: description, enabled, chat_enabled, visibility, version, keywords,
    tools, model (name, temperature, max_tokens), scope, interface, engine,
    effort, thinking_budget, max_budget_usd, max_input_length, timeout_seconds,
    retry_budget. Not synced: system prompts (config/prompts), agent_type,
    invocation, execution.
    It never creates or deletes a file, and it refuses a file whose result would
    fail validation, listing the reason.

    \b
    Examples:
        python admin.py catalog sync-yaml --dry-run
        python admin.py catalog sync-yaml
        python admin.py catalog sync-yaml --agent platform.health.agent
        python admin.py catalog sync-yaml --check
    """
    from modules.clients.cli.catalog_cmds import run_sync_yaml

    run_sync_yaml(
        ctx.logger,
        agent_name=agent_name,
        dry_run=dry_run,
        check=check,
        output_format=ctx.output_format,
    )


@catalog.command("set-provider")
@click.argument("provider")
@click.option(
    "--model-map",
    type=str,
    default=None,
    help="Comma-separated old=new bare model names, e.g. 'claude-haiku-4-5=gpt-5-nano'.",
)
@click.option("--dry-run", is_flag=True, help="Show changes without applying them")
@click.pass_obj
def catalog_set_provider(ctx, provider, model_map, dry_run):
    """Switch every agent to a provider from the model registry.

    Each model keeps its name if the provider has it, otherwise it maps by
    --model-map, otherwise by a name that matches ignoring punctuation
    (claude-opus-4-6 and claude-opus-4.6). If any agent has no match, nothing
    is changed and every gap is listed. Run 'catalog providers' for the
    providers and models available.

    \b
    Examples:
        python admin.py catalog set-provider copilot --dry-run
        python admin.py catalog set-provider anthropic
        python admin.py catalog set-provider foundry --model-map claude-opus-4-6=gpt-5.4,claude-sonnet-4-6=gpt-5-mini,claude-haiku-4-5=gpt-5-nano
    """  # noqa: E501
    import asyncio
    import sys

    async def _run():
        from modules.backend.core.exceptions import ValidationError
        from modules.backend.services.model_provider import ModelProviderService
        from modules.clients.cli.api_client import api_client

        try:
            async with ModelProviderService.factory() as svc:
                changes = await svc.plan_switch(
                    provider=provider, model_map=svc.parse_model_map(model_map)
                )
        except ValidationError as e:
            click.echo(str(e), err=True)
            sys.exit(1)

        if not dry_run and changes:
            async with api_client() as api:
                for change in changes:
                    await api.patch(
                        f"/admin/catalog/{change.agent_name}",
                        body={"model_config_json": change.new_config},
                    )

        for change in changes:
            click.echo(f"  {change.agent_name}: {change.current_model} -> {change.new_model}")
        label = "Would change" if dry_run else "Changed"
        click.echo(f"\n{label} {len(changes)} agent(s)")

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
