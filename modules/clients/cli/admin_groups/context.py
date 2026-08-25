"""Admin CLI — Context group — inspect what agents see.

Split out of root admin.py (Plan 84 Phase 5.5). Pure move, no behavior change.
"""

import click

from modules.clients.cli.cli_context import ShowHelpOnMissingArgs

# =============================================================================
# Context group — inspect what agents see
# =============================================================================


@click.group("context", cls=ShowHelpOnMissingArgs, invoke_without_command=True)
@click.pass_context
def context(ctx):
    """Inspect agent context: Code Map, PQI scores, dependencies.

    \b
    Examples:
        python admin.py context show
        python admin.py context show --mission <id>
        python admin.py context assembled --mission <id>
        python admin.py context codemap
        python admin.py context codemap --generate
        python admin.py context pqi
        python admin.py context deps
    """
    if ctx.invoked_subcommand is None:
        # Default to "show" when no subcommand given
        ctx.invoke(context_show)


@context.command("show")
@click.option(
    "--mission", "mission_id", default=None, help="Mission ID for full assembled context."
)
@click.pass_obj
def context_show(ctx, mission_id):
    """Show all context layers and token costs.

    Without --mission: global view (disk-only, no DB).
    With --mission: full assembled context packet from DB + disk.
    """
    from modules.clients.cli.context import run_context

    run_context(ctx.logger, "show", output_format=ctx.output_format, mission_id=mission_id)


@context.command("assembled")
@click.option("--mission", "mission_id", required=True, help="Mission ID.")
@click.option(
    "--tags",
    "domain_tags",
    default=None,
    help="Comma-separated domain tags (e.g. code,implementation).",
)
@click.pass_obj
def context_assembled(ctx, mission_id, domain_tags):
    """Build the full assembled context packet for a mission.

    Shows exactly what an agent receives: PCD + task + Code Map + history.
    Requires a running database.
    """
    from modules.clients.cli.context import run_context

    tags = domain_tags.split(",") if domain_tags else None
    run_context(
        ctx.logger,
        "assembled",
        output_format=ctx.output_format,
        mission_id=mission_id,
        domain_tags=tags,
    )


@context.command("codemap")
@click.option("--generate", is_flag=True, help="Regenerate before showing.")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format.",
)
@click.pass_obj
def context_codemap(ctx, generate, format_type):
    """Show or generate the Code Map."""
    from modules.clients.cli.context import run_context

    run_context(
        ctx.logger,
        "codemap",
        output_format=ctx.output_format,
        generate=generate,
        format_type=format_type,
    )


@context.command("pqi")
@click.pass_obj
def context_pqi(ctx):
    """Run the PyQuality Index scorer."""
    from modules.clients.cli.context import run_context

    run_context(ctx.logger, "pqi", output_format=ctx.output_format)


@context.command("deps")
@click.pass_obj
def context_deps(ctx):
    """Show dependency graph analysis."""
    from modules.clients.cli.context import run_context

    run_context(ctx.logger, "deps", output_format=ctx.output_format)
