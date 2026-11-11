"""Workflow versioning policy (Plan 88 step 88.2.8, reference architecture doc 29).

Every ``workflow.patched`` id is a registered string literal with a recorded
replay history, and no patch is ever deprecated inside the plan that added it.
"""

import ast
from pathlib import Path

import pytest

from modules.backend.core.config import find_project_root
from modules.backend.temporal.versioning import PATCH_ID_PATTERN, PATCH_IDS

PROJECT_ROOT = find_project_root()
TEMPORAL_DIR = PROJECT_ROOT / Path("modules/backend/temporal")
WORKFLOW_FILES = sorted(TEMPORAL_DIR.glob("*workflow*.py"))
TEMPORAL_FILES = sorted(TEMPORAL_DIR.glob("*.py"))
HISTORY_DIR = PROJECT_ROOT / Path("tests/fixtures/temporal_histories/mission_run")


def _calls_named(path: Path, name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(), filename=str(path))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        ):
            calls.append(node)
    return calls


def test_workflow_files_discovered():
    assert len(WORKFLOW_FILES) >= 6


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_patch_calls_use_registered_literal_ids(path: Path):
    for call in _calls_named(path, "patched"):
        assert (
            len(call.args) == 1 and not call.keywords
        ), f"{path.name}:{call.lineno} workflow.patched takes exactly one positional id"
        arg = call.args[0]
        assert isinstance(arg, ast.Constant) and isinstance(
            arg.value, str
        ), f"{path.name}:{call.lineno} patch id must be a string literal"
        assert (
            arg.value in PATCH_IDS
        ), f"{path.name}:{call.lineno} patch id {arg.value!r} is not in versioning.PATCH_IDS"


@pytest.mark.parametrize("patch_id", sorted(PATCH_IDS))
def test_registered_ids_match_pattern(patch_id: str):
    assert PATCH_ID_PATTERN.fullmatch(patch_id)


@pytest.mark.parametrize(
    ("candidate", "valid"),
    [
        ("p88-run-memory", True),
        ("p100-budget-caps", True),
        ("p8-run-memory", False),
        ("p88_run_memory", False),
        ("p88-Run-Memory", False),
        ("p88-", False),
        ("run-memory", False),
    ],
)
def test_patch_id_pattern(candidate: str, valid: bool):
    assert bool(PATCH_ID_PATTERN.fullmatch(candidate)) is valid


@pytest.mark.parametrize("patch_id", sorted(PATCH_IDS))
def test_registered_ids_have_histories(patch_id: str):
    assert (HISTORY_DIR / f"{patch_id}.json").is_file()


@pytest.mark.parametrize("path", TEMPORAL_FILES, ids=lambda p: p.name)
def test_no_deprecate_patch(path: Path):
    assert _calls_named(path, "deprecate_patch") == []
