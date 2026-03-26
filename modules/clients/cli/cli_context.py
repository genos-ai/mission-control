"""Shared CLI context — used by both mc.py and cli.py (admin.py)."""

from modules.backend.core.config import validate_project_root
from modules.backend.core.logging import bind_context, get_logger, setup_logging


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
