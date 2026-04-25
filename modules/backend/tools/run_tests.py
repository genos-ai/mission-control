"""
Tool: run_tests

Run the unit test suite and return results.
"""

import subprocess
import sys
from pathlib import Path


async def run_tests(project_root: Path) -> dict:
    """Run the unit test suite and return results.

    Returns:
        Dict with passed (bool), exit_code (int), and output (str tail).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )

    output_lines = result.stdout.splitlines()
    tail = "\n".join(output_lines[-50:]) if len(output_lines) > 50 else result.stdout
    passed = result.returncode == 0

    return {
        "passed": passed,
        "exit_code": result.returncode,
        "output": tail,
    }
