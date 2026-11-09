"""Workflow modules read no config (Plan 88 step 88.1.8, contract 3.3.2).

Replay must not depend on the worker's config: every value a workflow needs
arrives in its pinned snapshot. 88.2.2 widens WORKFLOW_FILES to *workflow*.py.
"""

import ast

from modules.backend.core.config import find_project_root

WORKFLOW_FILES = (
    "modules/backend/temporal/mission_run_workflow.py",
    "modules/backend/temporal/mission_schedule_tick_workflow.py",
)
FORBIDDEN = frozenset({"get_app_config", "get_default_budget_usd"})


def test_workflows_do_not_import_config():
    root = find_project_root()
    offenders: list[str] = []
    for rel in WORKFLOW_FILES:
        tree = ast.parse((root / rel).read_text(), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                offenders.extend(
                    f"{rel}:{node.lineno} imports {alias.name}"
                    for alias in node.names
                    if alias.name in FORBIDDEN
                )
    assert offenders == []
