"""Plan 88 step 88.0.10: the API process and dispatch never run blind reconcilers."""

import ast

from modules.backend.core.config import find_project_root


def _reconcile_names(rel_path: str) -> list[str]:
    tree = ast.parse((find_project_root() / rel_path).read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and "reconcile" in node.id:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and "reconcile" in node.attr:
            found.append(node.attr)
    return found


def test_main_does_not_reference_reconcilers():
    assert _reconcile_names("modules/backend/main.py") == []


def test_dispatch_does_not_reconcile():
    assert _reconcile_names("modules/backend/services/mission_plan_dispatch.py") == []
