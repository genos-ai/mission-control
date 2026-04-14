#!/usr/bin/env python3
"""Fast pre-commit rule checker — pure Python regex checks on staged files.

Designed for sub-second execution as a git pre-commit hook.
For the full rule suite, use scripts/code_rules.py.

Usage:
    python scripts/code_rules_fast.py            # Check staged files
    python scripts/code_rules_fast.py --all      # Check all module files
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Violation:
    rule_id: str
    severity: str
    file: str
    line: int
    message: str


# ── Checks ────────────────────────────────────────────────────────────────


def check_file_size(path: Path, rel: str) -> list[Violation]:
    """002.2 — Python files must not exceed 1000 lines."""
    if not rel.startswith("modules/"):
        return []
    lines = path.read_text().splitlines()
    if len(lines) > 1000:
        return [Violation(
            "002.2", "error", rel, 1,
            f"File has {len(lines)} lines (limit: 1000)",
        )]
    return []


def check_relative_imports(path: Path, rel: str) -> list[Violation]:
    """001.1 — No relative imports anywhere in modules/."""
    if not rel.startswith("modules/"):
        return []
    violations = []
    pattern = re.compile(r"^\s*from\s+\.")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.match(line):
            violations.append(Violation(
                "001.1", "error", rel, i,
                "Relative import — use absolute: from modules.backend.xxx import ...",
            ))
    return violations


def check_direct_logging(path: Path, rel: str) -> list[Violation]:
    """001.2 — No direct import logging — use get_logger()."""
    if not rel.startswith("modules/"):
        return []
    if "core/logging.py" in rel or "services/compliance.py" in rel:
        return []
    violations = []
    pattern = re.compile(r"^import logging\s*$")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.match(line):
            violations.append(Violation(
                "001.2", "error", rel, i,
                "Direct import logging — use: from modules.backend.core.logging import get_logger",
            ))
    return violations


def check_bare_except(path: Path, rel: str) -> list[Violation]:
    """002.3 — No bare except: clauses."""
    violations = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if re.match(r"^\s*except\s*:", line):
            violations.append(Violation(
                "002.3", "warning", rel, i, "Bare except: clause",
            ))
    return violations


def check_swallowed_exception(path: Path, rel: str) -> list[Violation]:
    """002.3b — No except Exception/BaseException followed by pass."""
    violations = []
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*except\s+(Exception|BaseException)", line):
            if i + 1 < len(lines) and lines[i + 1].strip() == "pass":
                violations.append(Violation(
                    "002.3", "error", rel, i + 1,
                    "Swallowed exception: except Exception/BaseException with pass",
                ))
    return violations


def check_datetime_violations(path: Path, rel: str) -> list[Violation]:
    """002.7/004.x — No datetime.now(), utcnow(), or timezone-aware patterns."""
    if not rel.startswith("modules/"):
        return []
    # Exclude files that reference these patterns in docstrings/comments
    skip_files = ("compliance.py", "temporal/workflow.py")
    if any(s in rel for s in skip_files):
        return []
    violations = []
    now_pattern = re.compile(r"datetime\.(now\(\)|utcnow\(\))")
    tz_pattern = re.compile(r"(pytz\.|datetime\.now\(timezone\.utc\)|\.astimezone|\.localize\()")
    skip_line = re.compile(r"(replace\(tzinfo=None\)|#\s|^\s*\"\"\")")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if skip_line.search(line):
            continue
        if now_pattern.search(line):
            violations.append(Violation(
                "004.3", "error", rel, i,
                "datetime.now()/utcnow() — use utc_now() from core.utils",
            ))
        elif tz_pattern.search(line):
            violations.append(Violation(
                "004.1", "error", rel, i,
                "Timezone-aware datetime — use naive UTC via utc_now()",
            ))
    return violations


def check_hardcoded_secrets(path: Path, rel: str) -> list[Violation]:
    """003.1 — No hardcoded secrets in source code."""
    violations = []
    pattern = re.compile(
        r"""(api_key|password|token|secret)\s*=\s*['"][^'"]{10,}['"]""", re.I
    )
    skip = re.compile(r"(os\.getenv|\.env|env\.example|your_|settings\.|Field\(|test_|conftest)")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.search(line) and not skip.search(line):
            violations.append(Violation(
                "003.1", "error", rel, i, "Possible hardcoded secret",
            ))
    return violations


def check_api_imports_repositories(path: Path, rel: str) -> list[Violation]:
    """001.6/005.1 — API layer must not import repositories directly."""
    if not rel.startswith("modules/backend/api/"):
        return []
    violations = []
    pattern = re.compile(r"from modules\.backend\.repositories\.")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.search(line):
            violations.append(Violation(
                "001.6", "error", rel, i,
                "API endpoint imports repository directly — use a service",
            ))
    return violations


def check_cli_imports_models(path: Path, rel: str) -> list[Violation]:
    """001.7 — CLI handlers must not import models or repositories."""
    if not rel.startswith("modules/clients/cli/"):
        return []
    if "health.py" in rel:
        return []
    violations = []
    pattern = re.compile(r"from modules\.backend\.(models|repositories)\.")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.search(line):
            violations.append(Violation(
                "001.7", "error", rel, i,
                "CLI handler imports models/repositories — use a service",
            ))
    return violations


def check_direct_rich(path: Path, rel: str) -> list[Violation]:
    """006.x — No direct Rich Console/Table/Panel in CLI handlers."""
    if not rel.startswith("modules/clients/cli/"):
        return []
    if any(s in rel for s in ("report.py", "gate.py", "display.py")):
        return []
    violations = []
    patterns = [
        (re.compile(r"\bConsole\(\s*\)"), "006.1", "Direct Console() — use get_console()"),
        (re.compile(r"\bTable\("), "006.2", "Direct Table() — use build_table()"),
        (re.compile(r"\bPanel\("), "006.3", "Direct Panel() — use shared primitives"),
    ]
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "from ", "import ")):
            continue
        for pat, rule_id, msg in patterns:
            if pat.search(line):
                violations.append(Violation(rule_id, "error", rel, i, msg))
    return violations


# ── Thin Client Enforcement ───────────────────────────────────────────────


def check_telegram_imports_models(path: Path, rel: str) -> list[Violation]:
    """008.1 — Telegram handlers must not import models or repositories."""
    if not rel.startswith("modules/clients/telegram/"):
        return []
    violations = []
    pattern = re.compile(r"from modules\.backend\.(models|repositories)\.")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.search(line):
            violations.append(Violation(
                "008.1", "error", rel, i,
                "Telegram handler imports models/repositories — use a service",
            ))
    return violations


def check_client_http_calls(path: Path, rel: str) -> list[Violation]:
    """008.2 — Client handlers must not make direct HTTP calls."""
    if not rel.startswith("modules/clients/"):
        return []
    # Exclude the API client wrapper itself
    if "api_client" in rel or "http_client" in rel:
        return []
    violations = []
    pattern = re.compile(r"(httpx\.(get|post|put|patch|delete|AsyncClient)|aiohttp\.ClientSession|requests\.(get|post))")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        if pattern.search(line):
            violations.append(Violation(
                "008.2", "error", rel, i,
                "Direct HTTP call in client — use a backend service",
            ))
    return violations


def check_endpoint_orchestration(path: Path, rel: str) -> list[Violation]:
    """008.3 — API endpoints must not contain multi-service orchestration."""
    if not rel.startswith("modules/backend/api/"):
        return []
    violations = []
    lines = path.read_text().splitlines()
    # Detect asyncio.gather in endpoints — sign of orchestration logic
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("#", "from ", "import ", '"""', "'''")):
            continue
        if "asyncio.gather(" in line:
            violations.append(Violation(
                "008.3", "warning", rel, i,
                "asyncio.gather in endpoint — move orchestration to a service",
            ))
    return violations


def check_endpoint_inline_transforms(path: Path, rel: str) -> list[Violation]:
    """008.4 — API endpoints must not build response dicts with computed fields."""
    if not rel.startswith("modules/backend/api/"):
        return []
    violations = []
    # Detect inline computation in response dicts:
    # - len(obj.attr) — derived field from model (not len(local_list))
    # - sum(), max(), min() — aggregation functions
    # - obj.attr +/-/*// expr — math on model fields
    compute_pattern = re.compile(
        r"""["']\w+["']\s*:\s*"""
        r"(len\(\w+\.\w+"  # len(obj.attr)
        r"|sum\(|max\(|min\("  # aggregation
        r"|\w+\.\w+\s*[-+*/]\s*\w+)"  # math on model fields
    )
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "from ", "import ", '"""', "'''")):
            continue
        if compute_pattern.search(line):
            violations.append(Violation(
                "008.4", "warning", rel, i,
                "Computed field in endpoint response — move to model property or service",
            ))
    return violations


def check_os_getenv_fallback(path: Path, rel: str) -> list[Violation]:
    """003.5 — No os.getenv() with hardcoded fallback defaults."""
    if not rel.startswith("modules/"):
        return []
    if any(s in rel for s in ("compliance.py", "test_", "conftest")):
        return []
    violations = []
    pattern = re.compile(r"os\.(getenv|environ\.get)\s*\(.+,\s*['\"]")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if pattern.search(line):
            violations.append(Violation(
                "003.5", "error", rel, i,
                "os.getenv() with hardcoded fallback — use get_settings() or get_app_config()",
            ))
    return violations


def check_isoformat_to_db_column(path: Path, rel: str) -> list[Violation]:
    """004.5 — No .isoformat() passed to model constructors or repo.create().

    DateTime columns require datetime objects. ISO strings cause asyncpg
    DataError at runtime. Use utc_now() directly, not utc_now().isoformat().
    """
    if not rel.startswith("modules/backend/"):
        return []
    # Only check services and persistence code — models/schemas are fine
    if not any(s in rel for s in ("services/", "persistence", "agents/")):
        return []
    violations = []
    # Match: field_name=something.isoformat() or field_name=utc_now().isoformat()
    # in contexts that look like model construction or repo calls
    pattern = re.compile(r"(started_at|completed_at|created_at|updated_at)\s*=.*\.isoformat\(\)")
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", '"""', "'''")):
            continue
        if pattern.search(line):
            violations.append(Violation(
                "004.5", "warning", rel, i,
                ".isoformat() on a timestamp field — verify the column accepts strings; DateTime columns need datetime objects",
            ))
    return violations


def check_logger_error_needs_mission_id(path: Path, rel: str) -> list[Violation]:
    """010.1 — logger.error/warning should include mission_id when available.

    The MissionEventHandler bridges WARNING+ logs with mission_id to the
    SSE stream. Without mission_id, errors are invisible to the user.

    Only flags files where mission_id is in scope (function params, self
    attrs, deps, or module-level variables). Infrastructure code without
    mission context (seeders, registry, code_map) is exempt.
    """
    if not rel.startswith("modules/backend/"):
        return []
    if not any(s in rel for s in ("services/", "agents/", "temporal/")):
        return []
    if any(s in rel for s in ("core/logging.py", "test_", "conftest",
                               "seeder", "catalog_seeder", "registry.py",
                               "code_map", "config_schema",
                               # Infrastructure without mission context:
                               "branch_manager", "container_backend",
                               "gate_prompt", "run_notifier",
                               "mission_plan_daemon", "workshop.py")):
        return []

    source = path.read_text()
    lines = source.splitlines()

    # Only flag files where mission_id is available somewhere in scope
    if "mission_id" not in source:
        return []

    violations = []
    error_pattern = re.compile(r"\blogger\.(error|warning)\(")
    mission_id_in_extra = re.compile(r"mission_id")

    for i, line in enumerate(lines, 1):
        if error_pattern.search(line):
            # Check the logger call and next 12 lines for mission_id
            # (extra dicts can span many lines in multi-key calls)
            context = "\n".join(lines[i - 1:min(i + 12, len(lines))])
            if not mission_id_in_extra.search(context):
                violations.append(Violation(
                    "010.1", "error", rel, i,
                    "logger.error/warning without mission_id — error will be invisible in stream",
                ))
    return violations


def check_execution_triggers_need_idempotency(path: Path, rel: str) -> list[Violation]:
    """009.1 — Endpoints that fire-and-forget agent work must support idempotency keys.

    An endpoint that calls asyncio.create_task() or run_execution() launches
    expensive background work. If the client retries on timeout, the work runs
    twice. These endpoints must declare an `idempotency: Idempotency` parameter
    so callers can safely retry with an Idempotency-Key header.
    """
    if not rel.startswith("modules/backend/api/"):
        return []

    violations = []
    lines = path.read_text().splitlines()

    # Patterns that indicate expensive background dispatch
    trigger_pattern = re.compile(
        r"\b(asyncio\.create_task|run_execution|start_temporal_execution)\b"
    )
    idempotency_pattern = re.compile(r"\bidempotency\b")

    # Walk function by function
    func_start = 0
    func_name = ""
    func_body: list[str] = []
    in_func = False

    for i, line in enumerate(lines):
        m = re.match(r"^async def (\w+)\s*\(", line)
        if m:
            # Check the function we just finished collecting
            if in_func and func_body:
                body = "\n".join(func_body)
                if trigger_pattern.search(body) and not idempotency_pattern.search(body):
                    violations.append(Violation(
                        "009.1", "error", rel, func_start,
                        f"'{func_name}' fires background execution but lacks "
                        "`idempotency: Idempotency` — add it to prevent duplicate runs on retry",
                    ))
            in_func = True
            func_start = i + 1
            func_name = m.group(1)
            func_body = [line]
        elif in_func:
            # Stop collecting at the next top-level definition (not indented)
            if line and not line[0].isspace() and line[0] not in ("#", "@", '"', "'"):
                in_func = False
                func_body = []
            else:
                func_body.append(line)

    # Check the last function in the file
    if in_func and func_body:
        body = "\n".join(func_body)
        if trigger_pattern.search(body) and not idempotency_pattern.search(body):
            violations.append(Violation(
                "009.1", "error", rel, func_start,
                f"'{func_name}' fires background execution but lacks "
                "`idempotency: Idempotency` — add it to prevent duplicate runs on retry",
            ))

    return violations


def check_agent_imports_models_repos(path: Path, rel: str) -> list[Violation]:
    """011.1 — Agent files must not import models or repositories directly.

    Agents are thin clients — all DB access goes through the service layer.
    This prevents agents from bypassing business rules, transaction
    boundaries, and audit logic that services enforce.
    """
    if not rel.startswith("modules/backend/agents/"):
        return []
    # deps files define dataclasses that may reference model types for type hints
    if "/deps/" in rel or rel.endswith("/deps.py"):
        return []
    violations = []
    patterns = [
        (re.compile(r"from modules\.backend\.models\."), "models"),
        (re.compile(r"from modules\.backend\.repositories\."), "repositories"),
        (re.compile(r"from sqlalchemy"), "sqlalchemy"),
    ]
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", '"""', "'''")):
            continue
        for pat, kind in patterns:
            if pat.search(line):
                violations.append(Violation(
                    "011.1", "warning", rel, i,
                    f"Agent imports {kind} directly — use a service",
                ))
    return violations


ALL_CHECKS = [
    check_file_size,
    check_relative_imports,
    check_direct_logging,
    check_bare_except,
    check_swallowed_exception,
    check_datetime_violations,
    check_isoformat_to_db_column,
    check_hardcoded_secrets,
    check_os_getenv_fallback,
    check_api_imports_repositories,
    check_cli_imports_models,
    check_direct_rich,
    check_telegram_imports_models,
    check_client_http_calls,
    check_endpoint_orchestration,
    check_endpoint_inline_transforms,
    check_execution_triggers_need_idempotency,
    check_logger_error_needs_mission_id,
    check_agent_imports_models_repos,
]


# ── File discovery ────────────────────────────────────────────────────────


def get_staged_py_files() -> list[Path]:
    """Get staged Python files from git."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    return [
        PROJECT_ROOT / f
        for f in result.stdout.strip().splitlines()
        if f.endswith(".py")
    ]


def get_all_module_files() -> list[Path]:
    """Get all Python files under modules/."""
    return sorted((PROJECT_ROOT / "modules").rglob("*.py"))


# ── Output ────────────────────────────────────────────────────────────────


RED = "\033[31m"
YEL = "\033[33m"
RST = "\033[0m"
BOLD = "\033[1m"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast pre-commit rule checker")
    parser.add_argument("--all", action="store_true", help="Check all module files")
    args = parser.parse_args()

    files = get_all_module_files() if args.all else get_staged_py_files()
    if not files:
        return 0

    all_violations: list[Violation] = []
    for path in files:
        if not path.exists():
            continue
        rel = str(path.relative_to(PROJECT_ROOT))
        for check_fn in ALL_CHECKS:
            all_violations.extend(check_fn(path, rel))

    errors = [v for v in all_violations if v.severity == "error"]
    warnings = [v for v in all_violations if v.severity == "warning"]

    if errors:
        print(f"\n{RED}{BOLD}Pre-commit check failed ({len(errors)} errors){RST}\n")
        for v in sorted(errors, key=lambda x: (x.rule_id, x.file)):
            print(f"  {RED}[{v.rule_id}]{RST} {v.file}:{v.line} — {v.message}")

    if warnings:
        print(f"\n{YEL}Warnings ({len(warnings)}):{RST}")
        for v in sorted(warnings, key=lambda x: (x.rule_id, x.file)):
            print(f"  {YEL}[{v.rule_id}]{RST} {v.file}:{v.line} — {v.message}")

    if errors:
        print(f"\n{RED}Commit blocked. Fix errors above or use --no-verify to skip.{RST}")
        return 1

    if all_violations:
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
