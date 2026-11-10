"""
Tool: run_tests

Run the unit test suite inside the agent's execution environment and return results.
"""

from typing import Any

from pydantic_ai import RunContext

from modules.backend.core.config import get_app_config
from modules.backend.services.execution_environment import run_in_environment

TOOL_DEF = {
    "name": "run_tests",
    "description": "Run the unit test suite and return results",
    "category": "code",
    "deps": ["environment_handle"],
}

RUN_TESTS_ARGV: list[str] = ["python", "-m", "pytest", "tests/unit", "-v", "--tb=short"]


async def run_tests(environment_handle: Any) -> dict:
    """Run the unit test suite inside the environment handle.

    Tests never run on the worker host: a ``None`` handle raises
    ``ExecutionEnvironmentError`` (Plan 88 contracts 3.8.5). The wall-clock
    limit is ``executions.run_tests_timeout_seconds``.

    Returns:
        Dict with passed (bool), exit_code (int), and output (str tail).
    """
    result = await run_in_environment(
        environment_handle,
        RUN_TESTS_ARGV,
        timeout_seconds=get_app_config().executions.run_tests_timeout_seconds,
    )

    output_lines = result.stdout.splitlines()
    tail = "\n".join(output_lines[-50:]) if len(output_lines) > 50 else result.stdout
    passed = result.exit_code == 0

    return {
        "passed": passed,
        "exit_code": result.exit_code,
        "output": tail,
    }


# ── Registry integration ─────────────────────────────────

_impl = run_tests


def register(agent):
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def run_tests(ctx: RunContext) -> dict:
        """Run the unit test suite and return results."""
        return await _impl(ctx.deps.environment_handle)
