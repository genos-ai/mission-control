#!/usr/bin/env python3
"""
Record a closed Temporal workflow history as a redacted replay fixture (Plan 88 step 88.2.9).

For histories from a real server: later workflow.patched fixtures and incident
captures. Fixtures for the stubbed MissionRunWorkflow scenarios come from
tests/integration/backend/temporal/test_record_mission_run_histories.py instead.

Usage:
    python scripts/record_workflow_history.py record --workflow-id WORKFLOW_ID \
        [--run-id RUN_ID] --name SLUG
    python scripts/record_workflow_history.py tree
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.backend.core.config import find_project_root  # noqa: E402
from modules.backend.core.logging import get_logger, setup_logging  # noqa: E402
from modules.backend.temporal.history_redaction import redact_history  # noqa: E402
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway  # noqa: E402

logger = get_logger(__name__)

HISTORY_DIR = Path("tests/fixtures/temporal_histories/mission_run")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


async def record(workflow_id: str, run_id: str | None, name: str) -> Path:
    if not SLUG_PATTERN.fullmatch(name):
        raise SystemExit(f"--name must match {SLUG_PATTERN.pattern}: {name!r}")
    gateway = await TemporalWorkflowGateway.connect()
    history, running = await gateway.fetch_history(workflow_id, run_id=run_id)
    if running:
        raise SystemExit(f"workflow {workflow_id} is still running; record it once it has closed")
    redacted = redact_history(json.loads(history.to_json()))
    target = find_project_root() / HISTORY_DIR / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(redacted, indent=2) + "\n")
    logger.info(
        "Workflow history recorded",
        extra={"workflow_id": workflow_id, "run_id": run_id, "path": str(target)},
    )
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="record_workflow_history.py", description=__doc__.strip().splitlines()[0]
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--debug", action="store_true", help="Debug logging")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    rec = commands.add_parser("record", help="Write a closed workflow's redacted history")
    rec.add_argument("--workflow-id", required=True, help="Temporal workflow id")
    rec.add_argument("--run-id", default=None, help="Run id; the latest run when omitted")
    rec.add_argument("--name", required=True, help="Fixture slug, written as <SLUG>.json")
    commands.add_parser("tree", help="List every subcommand and flag")
    return parser


def render_tree(parser: argparse.ArgumentParser) -> str:
    """Introspect the parser (rule 010.1); never a hand-maintained list."""
    lines = [parser.prog]
    lines += [f"  {_flags(a)}" for a in parser._actions if a.option_strings and a.dest != "help"]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {c.dest: c.help for c in action._choices_actions}
            for name, sub in action.choices.items():
                lines.append(f"  {name}: {helps.get(name, '')}")
                lines += [
                    f"    {_flags(a)}"
                    for a in sub._actions
                    if a.option_strings and a.dest != "help"
                ]
    return "\n".join(lines)


def _flags(action: argparse.Action) -> str:
    required = " (required)" if action.required else ""
    return f"{', '.join(action.option_strings)}{required}: {action.help}"


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    level = "DEBUG" if args.debug else "INFO" if args.verbose else "WARNING"
    setup_logging(level=level, format_type="console")
    if args.command == "tree":
        print(render_tree(parser))
    elif args.command == "record":
        target = asyncio.run(record(args.workflow_id, args.run_id, args.name))
        print(target)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
