"""Shared CLI primitives — used by both mc.py and cli.py (admin.py)."""

import click

from modules.backend.core.config import validate_project_root
from modules.backend.core.logging import bind_context, get_logger, setup_logging


class ShowHelpOnMissingArgs(click.Group):
    """Show full help instead of terse error when required args are missing."""

    def resolve_command(self, ctx, args):
        cmd_name, cmd, remaining = super().resolve_command(ctx, args)
        if cmd is not None and not isinstance(cmd, click.Group):
            required_args = [
                p for p in cmd.params
                if isinstance(p, click.Argument) and p.required
            ]
            if required_args and len(remaining) < len(required_args):
                with click.Context(cmd, info_name=cmd_name, parent=ctx) as sub_ctx:
                    click.echo(cmd.get_help(sub_ctx))
                ctx.exit(0)
        return cmd_name, cmd, remaining


class CliContext:
    """Shared context passed to all subcommands."""

    def __init__(
        self,
        verbose: bool = False,
        debug: bool = False,
        quiet: bool = False,
        output_format: str = "human",
        source: str = "cli",
    ):
        level = "DEBUG" if debug else "INFO" if verbose else "WARNING"
        validate_project_root()
        setup_logging(level=level, format_type="console")
        bind_context(source=source)
        self.logger = get_logger(source)
        self.output_format = output_format
        self.quiet = quiet
        self.verbose = verbose
