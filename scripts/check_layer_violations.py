"""Layer violation detector — enforces strict API → Service → Repository layering.

Scans API endpoints and client modules for forbidden imports of repositories
or models. These layers must only be accessed through the service layer.

Usage:
    python scripts/check_layer_violations.py          # Check all
    python scripts/check_layer_violations.py --quiet  # Exit code only

Exit codes:
    0 — No violations found
    1 — Violations found (prints details to stderr)

Integrate as a pre-commit hook or CI check to prevent layer violations
from being committed.
"""

import ast
import sys
from pathlib import Path

# Each entry maps a directory scope to the import prefixes that are forbidden
# within that scope.
FORBIDDEN_IMPORTS: dict[str, list[str]] = {
    "modules/backend/api/": [
        "modules.backend.repositories",
        "modules.backend.models",
    ],
    "modules/clients/": [
        "modules.backend.repositories",
        "modules.backend.models",
    ],
}

# Exceptions: imports that are permitted despite matching a forbidden prefix.
# For example, schema imports or protocol imports that are intentionally shared.
ALLOWED_EXCEPTIONS: set[str] = {
    "modules.backend.models.base",  # TimestampMixin etc. may be needed for type hints
}


def find_project_root() -> Path:
    """Walk up from this script to find .project_root marker."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".project_root").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent


def check_file(path: Path, forbidden: list[str]) -> list[str]:
    """Check a single Python file for forbidden imports.

    Returns a list of violation strings.
    """
    violations = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            for prefix in forbidden:
                if module.startswith(prefix) and module not in ALLOWED_EXCEPTIONS:
                    violations.append(
                        f"  {path}:{node.lineno}: forbidden import '{module}'"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden:
                    if alias.name.startswith(prefix) and alias.name not in ALLOWED_EXCEPTIONS:
                        violations.append(
                            f"  {path}:{node.lineno}: forbidden import '{alias.name}'"
                        )
    return violations


def main() -> int:
    root = find_project_root()
    errors: list[str] = []
    quiet = "--quiet" in sys.argv

    for scope, forbidden in FORBIDDEN_IMPORTS.items():
        scope_path = root / scope
        if not scope_path.exists():
            continue
        for py_file in scope_path.rglob("*.py"):
            errors.extend(check_file(py_file, forbidden))

    if errors:
        if not quiet:
            print(
                f"Layer violations found ({len(errors)}):\n",
                file=sys.stderr,
            )
            for e in errors:
                print(e, file=sys.stderr)
            print(
                "\nFix: Move repository/model access into the appropriate "
                "service. API endpoints and clients must only import from "
                "services and schemas.",
                file=sys.stderr,
            )
        return 1

    if not quiet:
        print("No layer violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
