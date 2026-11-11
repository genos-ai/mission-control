"""Workflow modules read no config (Plan 88 steps 88.1.8 and 88.2.2, contract 3.3.2).

Replay must not depend on the worker's config: every value a workflow needs
arrives in its pinned input snapshot. Every *workflow*.py module under
temporal/ is checked.
"""

import ast
from pathlib import Path

import pytest

from modules.backend.core.config import find_project_root

TEMPORAL_DIR = find_project_root() / Path("modules/backend/temporal")
WORKFLOW_FILES = sorted(TEMPORAL_DIR.glob("*workflow*.py"))
FORBIDDEN = frozenset({"get_app_config", "get_default_budget_usd", "get_settings"})


def _forbidden_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names if alias.name in FORBIDDEN)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            found.add(node.attr)
    return found


def test_workflow_files_discovered():
    assert len(WORKFLOW_FILES) >= 6


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_forbidden_config_access(path: Path):
    assert _forbidden_names(path) == set()
