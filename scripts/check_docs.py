#!/usr/bin/env python3
"""Verify documentation claims that drift silently.

Two defect classes caused every documentation defect found in the September 2026
audit, and both are mechanically detectable:

1. Dead relative links. Files were renamed to add ``core-``/``opt-``/``agentic-``
   infixes and inbound links were never updated, leaving 87 of 110 cross-links in
   the reference architecture broken.
2. Documented commands that do not exist. ``AGENTS.md`` advertised
   ``scripts/generate_code_map.py`` and ``scripts/score_quality.py``, neither of
   which was ever a real file.

Run with no arguments to check the live documentation set. Exits non-zero on any
finding so it can gate a build.

    python scripts/check_docs.py
    python scripts/check_docs.py --all      # include archive, plans, research
    python scripts/check_docs.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

# Directories excluded from the default run. Archived plans are historical
# records and are expected to reference paths that no longer exist; research and
# plan documents cite code that has since moved. Checking them produces noise
# rather than findings, so they are opt-in via --all.
DEFAULT_EXCLUDED_DIRS = (
    "docs/99-archive",
    "docs/08-plans",
    "docs/09-research",
    "docs/07-skills",
    "node_modules",
    ".venv",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)

ALWAYS_EXCLUDED_DIRS = (
    "node_modules",
    ".venv",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)

# Link-checked but not script-checked. The reference architecture is a universal
# standards library, so `python cli.py ...` there means "your project's CLI", not
# a file in this repository. Script-existence is only meaningful in documents
# that give operational instructions for *this* repo.
SCRIPT_CHECK_EXCLUDED_DIRS = ("docs/10-reference-architecture",)

# Illustrative names used inside docstring templates.
PLACEHOLDER_SCRIPTS = frozenset({"script_name.py", "scripts/script_name.py"})

LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# `python scripts/foo.py` or `python foo.py` inside a fenced block or prose.
SCRIPT_INVOCATION_PATTERN = re.compile(r"\bpython3?\s+((?:scripts/)?[\w./-]+\.py)\b")

# Link targets that are deliberately not filesystem paths.
NON_PATH_PREFIXES = ("http://", "https://", "mailto:", "#", "/")


@dataclass
class Findings:
    """Accumulated problems, grouped by the check that produced them."""

    dead_links: list[dict[str, object]] = field(default_factory=list)
    missing_scripts: list[dict[str, object]] = field(default_factory=list)
    links_checked: int = 0
    scripts_checked: int = 0
    files_checked: int = 0

    @property
    def total(self) -> int:
        return len(self.dead_links) + len(self.missing_scripts)


def find_project_root(start: Path) -> Path:
    """Locate the repository root by its `.project_root` marker."""
    for candidate in (start, *start.parents):
        if (candidate / ".project_root").exists():
            return candidate
    raise SystemExit("could not locate .project_root above " + str(start))


def markdown_files(root: Path, excluded: tuple[str, ...]) -> list[Path]:
    """Every tracked-looking markdown file outside the excluded directories."""
    out = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(d) or f"/{d}/" in f"/{rel}" for d in excluded):
            continue
        out.append(path)
    return out


def resolves(doc: Path, target: str) -> bool:
    """True if a relative link target exists, percent-encoded or not."""
    return (doc.parent / target).exists() or (doc.parent / urllib.parse.unquote(target)).exists()


def check_links(doc: Path, root: Path, findings: Findings) -> None:
    """Every relative markdown link must resolve to a real path."""
    for line_no, line in enumerate(doc.read_text(errors="ignore").splitlines(), 1):
        for match in LINK_PATTERN.finditer(line):
            target = match.group(1).strip()
            # Absolute paths are runtime endpoints (/docs, /openapi.json), not files.
            if target.startswith(NON_PATH_PREFIXES):
                continue
            # Python type annotations in code blocks look like links to this
            # regex, e.g. `ctx: RunContext[[Deps]], [args]`. A real target has
            # no raw whitespace or nested brackets.
            if any(c in target for c in " \t["):
                continue
            base = target.partition("#")[0].strip()
            if not base:
                continue
            findings.links_checked += 1
            if not resolves(doc, base):
                findings.dead_links.append(
                    {
                        "file": doc.relative_to(root).as_posix(),
                        "line": line_no,
                        "target": base,
                    }
                )


def check_script_invocations(doc: Path, root: Path, findings: Findings) -> None:
    """Every `python <path>.py` command in the docs must name a real file."""
    for line_no, line in enumerate(doc.read_text(errors="ignore").splitlines(), 1):
        for match in SCRIPT_INVOCATION_PATTERN.finditer(line):
            script = match.group(1)
            # Placeholders such as `python <entry>.py` are illustrative.
            if "<" in script or ">" in script or script.startswith("-"):
                continue
            if script in PLACEHOLDER_SCRIPTS:
                continue
            findings.scripts_checked += 1
            if not (root / script).exists():
                findings.missing_scripts.append(
                    {
                        "file": doc.relative_to(root).as_posix(),
                        "line": line_no,
                        "script": script,
                    }
                )


def report(findings: Findings, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "files_checked": findings.files_checked,
                    "links_checked": findings.links_checked,
                    "scripts_checked": findings.scripts_checked,
                    "dead_links": findings.dead_links,
                    "missing_scripts": findings.missing_scripts,
                },
                indent=2,
            )
        )
        return

    print(
        f"checked {findings.files_checked} documents: "
        f"{findings.links_checked} relative links, "
        f"{findings.scripts_checked} script invocations"
    )

    if findings.dead_links:
        print(f"\nDead links ({len(findings.dead_links)}):")
        for item in findings.dead_links:
            print(f"  {item['file']}:{item['line']}  ->  {item['target']}")

    if findings.missing_scripts:
        print(f"\nDocumented scripts that do not exist ({len(findings.missing_scripts)}):")
        for item in findings.missing_scripts:
            print(f"  {item['file']}:{item['line']}  ->  {item['script']}")

    if findings.total == 0:
        print("\nOK — no findings.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="include archive, plans, research and skills (expected to have stale references)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    root = find_project_root(Path(__file__).resolve().parent)
    excluded = ALWAYS_EXCLUDED_DIRS if args.all else DEFAULT_EXCLUDED_DIRS

    findings = Findings()
    for doc in markdown_files(root, excluded):
        findings.files_checked += 1
        check_links(doc, root, findings)
        rel = doc.relative_to(root).as_posix()
        if not rel.startswith(SCRIPT_CHECK_EXCLUDED_DIRS):
            check_script_invocations(doc, root, findings)

    report(findings, args.json)
    return 1 if findings.total else 0


if __name__ == "__main__":
    sys.exit(main())
