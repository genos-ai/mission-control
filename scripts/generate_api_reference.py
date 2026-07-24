#!/usr/bin/env python3
"""Generate an API endpoint inventory from the FastAPI app.

Introspects the mounted FastAPI routers and emits a Markdown table per
router prefix.  Default output goes to .codemap/api_reference.md (same
folder as map.md and quality.md).

Usage:
    python scripts/generate_api_reference.py              # Markdown to .codemap/api_reference.md
    python scripts/generate_api_reference.py --stdout     # Markdown to stdout
    python scripts/generate_api_reference.py --format json# JSON to .codemap/api_reference.json
    python scripts/generate_api_reference.py --check      # Exit 1 if doc is stale
    python scripts/generate_api_reference.py --update     # Overwrite generated section in 007-api-reference.md  # noqa: E501
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DOC_PATH = PROJECT_ROOT / "docs" / "02-architecture" / "007-api-reference.md"

# Marker comments in the doc that delimit the generated section
BEGIN_MARKER = "<!-- GENERATED:BEGIN"
END_MARKER = "<!-- GENERATED:END -->"


def get_app_routes() -> list[dict]:
    """Import the FastAPI app and extract all routes."""
    # Minimal env to allow import without full config
    import os

    os.environ.setdefault("MC_ENV", "test")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
    os.environ.setdefault("SECRET_KEY", "generate-api-ref-dummy-key")

    try:
        from modules.backend.api.v1 import router as v1_router
    except Exception as e:
        print(f"Warning: Could not import v1 router: {e}", file=sys.stderr)
        print("Falling back to AST-based extraction.", file=sys.stderr)
        return extract_routes_from_ast()

    routes = []
    for route in v1_router.routes:
        if not hasattr(route, "methods"):
            continue
        for method in sorted(route.methods):
            if method in ("HEAD", "OPTIONS"):
                continue

            # Determine auth level from dependencies
            auth = _resolve_auth(route)

            routes.append(
                {
                    "method": method,
                    "path": f"/api/v1{route.path}",
                    "name": route.name or "",
                    "tags": list(route.tags) if hasattr(route, "tags") else [],
                    "auth": auth,
                }
            )

    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def _resolve_auth(route) -> str:
    """Inspect route dependencies to determine auth level."""
    deps = []
    if hasattr(route, "dependant") and hasattr(route.dependant, "dependencies"):
        for dep in route.dependant.dependencies:
            call = dep.call if hasattr(dep, "call") else None
            if call is not None:
                name = (
                    getattr(call, "__name__", "") or getattr(call, "__func__", "").__name__
                    if hasattr(getattr(call, "__func__", None), "__name__")
                    else str(call)
                )
                deps.append(name)

    # Check function signature annotations for known dependency types
    endpoint = getattr(route, "endpoint", None)
    if endpoint:
        import inspect

        sig = inspect.signature(endpoint)
        for param in sig.parameters.values():
            annotation = param.annotation
            ann_str = str(annotation)
            if "AdminRole" in ann_str or "require_admin" in ann_str:
                return "Admin"
            if "CurrentUser" in ann_str and "Optional" not in ann_str:
                return "Authenticated"
            if "SseUser" in ann_str:
                return "SSE"

    if any("admin" in d.lower() for d in deps):
        return "Admin"
    if any("current_user" in d.lower() for d in deps):
        return "Authenticated"
    if any("sse" in d.lower() for d in deps):
        return "SSE"

    return "Public"


def extract_routes_from_ast() -> list[dict]:
    """Fallback: parse endpoint files with AST to extract route decorators."""
    endpoints_dir = PROJECT_ROOT / "modules" / "backend" / "api" / "v1" / "endpoints"
    init_file = PROJECT_ROOT / "modules" / "backend" / "api" / "v1" / "__init__.py"

    # Parse __init__.py to get prefix mappings
    prefixes = {}
    if init_file.exists():
        content = init_file.read_text()
        # Match: router.include_router(xxx.router, prefix="/yyy", ...)
        for match in re.finditer(
            r'include_router\(\s*(\w+)\.router\s*,\s*prefix="([^"]*)"', content
        ):
            module_name, prefix = match.groups()
            prefixes[module_name] = prefix

    routes = []
    for py_file in sorted(endpoints_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module_name = py_file.stem
        prefix = prefixes.get(module_name, "")

        try:
            tree = __import__("ast").parse(py_file.read_text())
        except SyntaxError:
            continue

        for node in __import__("ast").walk(tree):
            if not isinstance(node, __import__("ast").AsyncFunctionDef) and not isinstance(
                node, __import__("ast").FunctionDef
            ):
                continue
            for decorator in node.decorator_list:
                method, path = _parse_route_decorator(decorator)
                if method:
                    full_path = f"/api/v1{prefix}{path}"
                    routes.append(
                        {
                            "method": method.upper(),
                            "path": full_path,
                            "name": node.name,
                            "tags": [module_name],
                            "auth": "—",
                        }
                    )

    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def _parse_route_decorator(node) -> tuple[str | None, str]:
    """Extract HTTP method and path from a route decorator AST node."""
    import ast

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        method_name = node.func.attr
        if method_name in ("get", "post", "put", "patch", "delete"):
            path = ""
            if node.args and isinstance(node.args[0], ast.Constant):
                path = node.args[0].value
            return method_name, path
    return None, ""


def group_routes(routes: list[dict]) -> dict[str, list[dict]]:
    """Group routes by their first two path segments."""
    groups: dict[str, list[dict]] = {}
    for route in routes:
        parts = route["path"].strip("/").split("/")
        # Use first meaningful segment after api/v1
        key = parts[2] if len(parts) > 2 else "root"
        groups.setdefault(key, []).append(route)
    return groups


def render_markdown(routes: list[dict]) -> str:
    """Render route inventory as markdown tables grouped by domain."""
    groups = group_routes(routes)
    lines = []

    lines.append("<!-- GENERATED:BEGIN — everything between GENERATED:BEGIN and GENERATED:END is")
    lines.append("     regenerated by scripts/generate_api_reference.py. Do not hand-edit. -->")
    lines.append("")

    for group_name in sorted(groups.keys()):
        group_routes_list = groups[group_name]
        lines.append(f"### {group_name}")
        lines.append("")
        lines.append("| Method | Path | Auth | Endpoint |")
        lines.append("|--------|------|------|----------|")
        for r in group_routes_list:
            lines.append(f"| {r['method']} | `{r['path']}` | {r['auth']} | `{r['name']}` |")
        lines.append("")

    lines.append(f"**Total endpoints: {len(routes)}**")
    lines.append("")
    lines.append("<!-- GENERATED:END -->")
    return "\n".join(lines)


def extract_generated_section(doc_text: str) -> str | None:
    """Extract the generated section from the doc."""
    start = doc_text.find(BEGIN_MARKER)
    end = doc_text.find(END_MARKER)
    if start == -1 or end == -1:
        return None
    return doc_text[start : end + len(END_MARKER)]


def check_mode(routes: list[dict]) -> bool:
    """Return True if the doc is up-to-date, False if stale."""
    if not DOC_PATH.exists():
        print(f"ERROR: {DOC_PATH} does not exist.", file=sys.stderr)
        return False

    doc_text = DOC_PATH.read_text()

    # Extract route paths from the generated section of the doc
    doc_routes = set()
    for match in re.finditer(r"\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)`", doc_text):
        method, path = match.groups()
        doc_routes.add((method, path))

    # Compare with current routes
    current_routes = {(r["method"], r["path"]) for r in routes}

    missing = current_routes - doc_routes
    extra = doc_routes - current_routes

    if missing:
        print("Endpoints in code but NOT in doc:", file=sys.stderr)
        for method, path in sorted(missing):
            print(f"  + {method} {path}", file=sys.stderr)

    if extra:
        print("Endpoints in doc but NOT in code:", file=sys.stderr)
        for method, path in sorted(extra):
            print(f"  - {method} {path}", file=sys.stderr)

    if not missing and not extra:
        print("API reference is up-to-date.", file=sys.stderr)
        return True

    print(
        f"\n{len(missing)} missing, {len(extra)} extra. "
        "Run `python scripts/generate_api_reference.py --update` to fix.",
        file=sys.stderr,
    )
    return False


def main():
    parser = argparse.ArgumentParser(description="Generate API endpoint inventory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if doc is up-to-date; exit 1 if stale",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Overwrite the generated section in 007-api-reference.md",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing to .codemap/",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Write output to file instead of default (.codemap/ folder)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    args = parser.parse_args()

    routes = get_app_routes()

    if not routes:
        print("No routes found. Check that the backend can be imported.", file=sys.stderr)
        sys.exit(1)

    if args.check:
        ok = check_mode(routes)
        sys.exit(0 if ok else 1)

    if args.update:
        if not DOC_PATH.exists():
            print(f"ERROR: {DOC_PATH} does not exist.", file=sys.stderr)
            sys.exit(1)
        md = render_markdown(routes)
        doc_text = DOC_PATH.read_text()
        existing = extract_generated_section(doc_text)
        if existing:
            doc_text = doc_text.replace(existing, md)
        else:
            doc_text += "\n\n" + md
        DOC_PATH.write_text(doc_text)
        print(f"Updated {DOC_PATH}", file=sys.stderr)
        return

    # Build output string
    if args.format == "json":
        import json

        output = json.dumps(routes, indent=2)
    else:
        output = render_markdown(routes)

    # Write to destination
    if args.stdout:
        print(output)
        return

    if args.output:
        out_path = Path(args.output)
    else:
        codemap_dir = PROJECT_ROOT / ".codemap"
        codemap_dir.mkdir(exist_ok=True)
        ext = "json" if args.format == "json" else "md"
        out_path = codemap_dir / f"api_reference.{ext}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(
        f"API reference written to {out_path} "
        f"({len(routes)} endpoints, ~{len(output) // 4} tokens)",
    )


if __name__ == "__main__":
    main()
