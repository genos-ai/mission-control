#!/usr/bin/env python3
"""
Plan 62 — Unified Execution Path E2E Test Bench.

Black-box verification that CLI and API execution paths both use
the plan infrastructure. All mutations go through mc.py or the HTTP
API — the DB is read-only (queries for verification gates only).

Uses a persistent mission (e2e-test-bench-plan62) that is created on
first run and reused thereafter. --reset archives the old mission and
creates a fresh one.

Gates (scored PASS/FAIL):
    SETUP  — Mission exists, correct agents, gate mode, budget
    CLI    — mc run creates plan, tracks task states, records cost
    API    — POST /plan/run-objective, async dispatch, supervisor fires
    LOOP   — Multi-wave: supervisor advances, plan version bumps
    PARITY — Plan infrastructure used, no legacy path

Usage:
    python scripts/verify_unified_execution.py                # all paths
    python scripts/verify_unified_execution.py --cli-only     # CLI path only
    python scripts/verify_unified_execution.py --api-only     # API + loop only
    python scripts/verify_unified_execution.py --reset        # fresh mission
    python scripts/verify_unified_execution.py --verbose      # show output
    python scripts/verify_unified_execution.py --debug        # full logging

Exit codes:
    0 — all gates passed
    N — N gates failed

Requirements:
    - Backend running at localhost:8100
    - PostgreSQL accessible
    - httpx installed (pip install httpx)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "http://localhost:8100/api/v1"

BENCH_CLI_MISSION = "e2e-bench-cli"
BENCH_API_MISSION = "e2e-bench-api"
BENCH_DESCRIPTION = "E2E test bench for Plan 62 unified execution path"
BENCH_BRIEF = "Test autonomous execution via plan infrastructure. Verify supervisor loop, budget tracking, and knowledge accumulation."
BENCH_BUDGET_USD = 5.0
BENCH_GATE_MODE = "autonomous"

# Agents required by the test scenarios (all auto-assigned on creation):
#   Task executors: planning, summarization, synthesis, verification
#   Loop infra:     supervisor (post-run gate), director (followup consumer)
REQUIRED_AGENTS = [
    "mission.planning.agent",
    "system.summarization.agent",
    "system.synthesis.agent",
    "system.verification.agent",
    "mission.supervisor.agent",
    "mission.director.agent",
]

# Test objectives — simple enough to complete quickly
CLI_OBJECTIVE = (
    "Summarize in 3 bullet points: what are the main benefits "
    "of structured logging vs print statements?"
)
API_OBJECTIVE = "List 3 advantages of async/await over callbacks in Python. Be concise."
WAVE2_OBJECTIVE = (
    "Cross-reference the async benefits with FastAPI and Django. "
    "Which framework benefits most from async? One paragraph."
)

PASS_ICON = "\u2713"
FAIL_ICON = "\u2717"


# ---------------------------------------------------------------------------
# Gate tracking
# ---------------------------------------------------------------------------


@dataclass
class Gate:
    id: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Section:
    name: str
    gates: list[Gate] = field(default_factory=list)

    def check(self, gate_id: str, name: str, passed: bool, detail: str = "") -> None:
        self.gates.append(Gate(gate_id, name, passed, detail))

    @property
    def pass_count(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for g in self.gates if not g.passed)


# ---------------------------------------------------------------------------
# DB read-only queries (verification only — NO writes)
# ---------------------------------------------------------------------------


async def db_scalar(sql: str) -> Any:
    from sqlalchemy import text

    from modules.backend.core.database import get_async_session

    async with get_async_session() as s:
        r = await s.execute(text(sql))
        row = r.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------


def mc(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_REPO_ROOT / "mc.py"), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


async def get_token() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/auth/login",
            json={
                "email": "admin@missioncontrol.dev",
                "password": "admin",
            },
        )
        return r.json().get("data", {}).get("access_token", "")


async def api_post(token: str, path: str, body: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{API_BASE}{path}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            return r.json()
    except httpx.ReadTimeout:
        return {"error": {"message": "HTTP timeout (300s) — planning agent may be slow"}}


async def api_patch(token: str, path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(
            f"{API_BASE}{path}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        return r.json()


async def wait_plan_idle(mission_id: str, max_wait: int = 180) -> bool:
    elapsed = 0
    while elapsed < max_wait:
        active = await db_scalar(f"""
            SELECT COUNT(*) FROM plan_task_states pts
            JOIN mission_plans mp ON pts.mission_plan_id = mp.id
            WHERE mp.mission_id = '{mission_id}'
            AND pts.status IN ('queued', 'running')
        """)
        if active == 0:
            return True
        await asyncio.sleep(10)
        elapsed += 10
        print(f"    ... waiting ({elapsed}s, {active} active)")
    return False


# ---------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------


async def _ensure_mission(
    name: str,
    reset: bool,
    verbose: bool,
) -> str | None:
    """Ensure a named mission exists, is active, and configured. Returns ID."""
    mission_id = await db_scalar(f"SELECT id FROM missions WHERE name = '{name}' LIMIT 1")

    if reset and mission_id:
        print(f"    Deleting old: {name}")
        mc("mission", "use", name)
        mc("mission", "delete", "--confirm")
        mission_id = None

    if not mission_id:
        print(f"    Creating: {name}")
        result = mc(
            "mission",
            "create",
            "--name",
            name,
            "--description",
            BENCH_DESCRIPTION,
            "--brief",
            BENCH_BRIEF,
            "--gate",
            BENCH_GATE_MODE,
            "--budget",
            str(BENCH_BUDGET_USD),
        )
        if verbose and result.stdout:
            for line in result.stdout.strip().split("\n")[:3]:
                print(f"      {line}")
        mission_id = await db_scalar(f"SELECT id FROM missions WHERE name = '{name}' LIMIT 1")

    if not mission_id:
        return None

    # Ensure active + correct config
    mc("mission", "use", name)
    gate = await db_scalar(f"SELECT gate_mode FROM missions WHERE id = '{mission_id}'")
    if gate != BENCH_GATE_MODE:
        mc("mission", "set-gate", BENCH_GATE_MODE)

    return mission_id


async def setup_bench(
    token: str,
    reset: bool,
    verbose: bool,
    need_cli: bool,
    need_api: bool,
) -> tuple[Section, str, str]:
    """Create/verify bench missions. Returns (section, cli_mission_id, api_mission_id)."""
    section = Section("SETUP")
    cli_id = ""
    api_id = ""

    if need_cli:
        cli_id = await _ensure_mission(BENCH_CLI_MISSION, reset, verbose) or ""
        section.check(
            "S1a",
            f"CLI mission: {BENCH_CLI_MISSION}",
            bool(cli_id),
            cli_id[:12] if cli_id else "not found",
        )

    if need_api:
        api_id = await _ensure_mission(BENCH_API_MISSION, reset, verbose) or ""
        section.check(
            "S1b",
            f"API mission: {BENCH_API_MISSION}",
            bool(api_id),
            api_id[:12] if api_id else "not found",
        )

    # Verify config and agents on whichever missions we have
    for label, mid in [("CLI", cli_id), ("API", api_id)]:
        if not mid:
            continue

        gate = await db_scalar(f"SELECT gate_mode FROM missions WHERE id = '{mid}'")
        section.check(
            f"S2:{label}",
            f"{label} gate = {BENCH_GATE_MODE}",
            gate == BENCH_GATE_MODE,
            f"got={gate}",
        )

        budget = await db_scalar(f"SELECT budget_ceiling_usd FROM missions WHERE id = '{mid}'")
        section.check(
            f"S3:{label}",
            f"{label} budget = ${BENCH_BUDGET_USD}",
            float(budget or 0) == BENCH_BUDGET_USD,
            f"got=${budget}",
        )

        for agent_name in REQUIRED_AGENTS:
            present = await db_scalar(f"""
                SELECT CASE WHEN COUNT(*) > 0 THEN true ELSE false END
                FROM mission_team_members mtm
                JOIN agent_catalog ac ON mtm.agent_catalog_id = ac.id
                WHERE mtm.mission_id = '{mid}'
                AND ac.agent_name = '{agent_name}'
                AND mtm.enabled = true
            """)
            section.check(f"S4:{label}:{agent_name}", f"{label} agent: {agent_name}", bool(present))

    return section, cli_id, api_id


# ---------------------------------------------------------------------------
# PATH A: CLI
# ---------------------------------------------------------------------------


async def test_cli(mission_id: str, verbose: bool) -> Section:
    section = Section("CLI (mc run)")

    mc("mission", "use", BENCH_CLI_MISSION)
    print("  Running: mc run ...")
    result = mc("run", CLI_OBJECTIVE, "--gate", "autonomous")
    if verbose:
        print(f"    exit={result.returncode}")
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-5:]:
                print(f"    {line}")

    # A1: Plan exists
    has_plan = await db_scalar(f"""
        SELECT CASE WHEN task_plan_json IS NOT NULL THEN true ELSE false END
        FROM mission_plans WHERE mission_id = '{mission_id}' LIMIT 1
    """)
    section.check("A1", "Plan created with task_plan_json", bool(has_plan))

    # A2: Task states
    state_count = await db_scalar(f"""
        SELECT COUNT(*) FROM plan_task_states pts
        JOIN mission_plans mp ON pts.mission_plan_id = mp.id
        WHERE mp.mission_id = '{mission_id}'
    """)
    section.check(
        "A2", "plan_task_states rows exist", (state_count or 0) > 0, f"count={state_count}"
    )

    # A3: Terminal tasks
    terminal = await db_scalar(f"""
        SELECT COUNT(*) FROM plan_task_states pts
        JOIN mission_plans mp ON pts.mission_plan_id = mp.id
        WHERE mp.mission_id = '{mission_id}'
        AND pts.status IN ('completed', 'failed', 'skipped')
    """)
    section.check("A3", "Tasks reached terminal state", (terminal or 0) > 0, f"count={terminal}")

    # A4: llm_calls recorded
    llm_count = await db_scalar(f"SELECT COUNT(*) FROM llm_calls WHERE mission_id = '{mission_id}'")
    section.check("A4", "llm_calls recorded", (llm_count or 0) > 0, f"count={llm_count}")

    # A5: Budget tracked
    spent = await db_scalar(f"""
        SELECT total_spent_usd FROM mission_plans
        WHERE mission_id = '{mission_id}' LIMIT 1
    """)
    section.check("A5", "total_spent_usd > 0", (spent or 0) > 0, f"${spent or 0:.4f}")

    # A6: No legacy executions row
    legacy = await db_scalar(f"SELECT COUNT(*) FROM executions WHERE mission_id = '{mission_id}'")
    section.check("A6", "No legacy executions row", legacy == 0, f"count={legacy}")

    return section


# ---------------------------------------------------------------------------
# PATH B: API
# ---------------------------------------------------------------------------


async def test_api(token: str, mission_id: str, verbose: bool) -> Section:
    section = Section("API (POST /plan/run-objective)")

    print("  Running objective via API (async)...")
    resp = await api_post(
        token,
        f"/missions/{mission_id}/plan/run-objective",
        {
            "objective": API_OBJECTIVE,
            "async_dispatch": True,
        },
    )
    data = resp.get("data") or {}
    error = resp.get("error") or {}
    outcome = data.get("outcome_status", error.get("message", "unknown"))
    if verbose:
        print(f"    {json.dumps(data, indent=2, default=str)}")

    section.check("B1", "outcome_status = dispatching", outcome == "dispatching", f"got={outcome}")

    if outcome == "dispatching":
        print("  Waiting for dispatch...")
        idle = await wait_plan_idle(mission_id)
        section.check("B2", "Plan reaches idle", idle)
    else:
        section.check("B2", "Plan reaches idle", False, f"skipped: {outcome}")

    # B3: Supervisor fires
    supervisor = await db_scalar(f"""
        SELECT COUNT(*) FROM execution_decisions d
        JOIN execution_records er ON d.execution_record_id = er.id
        WHERE er.mission_id = '{mission_id}'
        AND UPPER(d.decision_type) = 'POST_RUN_SUPERVISOR'
    """)
    section.check(
        "B3", "Supervisor decision recorded", (supervisor or 0) > 0, f"count={supervisor}"
    )

    # B4: Budget tracked on plan
    spent = await db_scalar(f"""
        SELECT total_spent_usd FROM mission_plans
        WHERE mission_id = '{mission_id}' LIMIT 1
    """)
    section.check("B4", "total_spent_usd > 0", (spent or 0) > 0, f"${spent or 0:.4f}")

    return section


# ---------------------------------------------------------------------------
# PATH C: Multi-wave
# ---------------------------------------------------------------------------


async def test_multiwave(token: str, mission_id: str, verbose: bool) -> Section:
    """Verify autonomy loop infrastructure after the first dispatch.

    After wave 1, the supervisor should have evaluated and made a decision.
    We check that the loop infrastructure fired correctly rather than
    forcing a second wave (which requires the supervisor to decide ADVANCE).
    """
    section = Section("LOOP (autonomy infrastructure)")

    # C1: Supervisor evaluated (iteration count >= 1)
    iterations = await db_scalar(f"""
        SELECT supervisor_iteration_count FROM mission_plans
        WHERE mission_id = '{mission_id}' LIMIT 1
    """)
    section.check(
        "C1",
        "Supervisor evaluated (iterations >= 1)",
        (iterations or 0) >= 1,
        f"count={iterations}",
    )

    # C2: Supervisor made a decision
    decisions = await db_scalar(f"""
        SELECT COUNT(*) FROM execution_decisions d
        JOIN execution_records er ON d.execution_record_id = er.id
        WHERE er.mission_id = '{mission_id}'
        AND UPPER(d.decision_type) = 'POST_RUN_SUPERVISOR'
    """)
    section.check("C2", "Supervisor decision recorded", (decisions or 0) > 0, f"count={decisions}")

    # C3: Execution record created by daemon dispatch
    records = await db_scalar(
        f"SELECT COUNT(*) FROM execution_records WHERE mission_id = '{mission_id}'"
    )
    section.check("C3", "Execution record from dispatch", (records or 0) >= 1, f"count={records}")

    # C4: Plan version >= 2 (refined by run_objective)
    version = await db_scalar(
        f"SELECT version FROM mission_plans WHERE mission_id = '{mission_id}' LIMIT 1"
    )
    section.check("C4", "Plan version >= 2 (refined)", (version or 0) >= 2, f"version={version}")

    return section


# ---------------------------------------------------------------------------
# PARITY
# ---------------------------------------------------------------------------


async def test_parity(cli_mission_id: str, api_mission_id: str) -> Section:
    """Compare CLI and API missions produce equivalent DB state shapes."""
    section = Section("PARITY (CLI vs API equivalence)")

    for label, mid in [("CLI", cli_mission_id), ("API", api_mission_id)]:
        if not mid:
            section.check(f"P1:{label}", f"{label} mission available", False)
            continue

        has_plan = await db_scalar(f"""
            SELECT CASE WHEN COUNT(*) > 0 THEN true ELSE false END
            FROM mission_plans WHERE mission_id = '{mid}'
        """)
        section.check(f"P1:{label}", f"{label} has mission_plans", bool(has_plan))

        states = await db_scalar(f"""
            SELECT COUNT(*) FROM plan_task_states pts
            JOIN mission_plans mp ON pts.mission_plan_id = mp.id
            WHERE mp.mission_id = '{mid}'
        """)
        section.check(
            f"P2:{label}", f"{label} has plan_task_states", (states or 0) > 0, f"count={states}"
        )

        calls = await db_scalar(f"SELECT COUNT(*) FROM llm_calls WHERE mission_id = '{mid}'")
        section.check(f"P3:{label}", f"{label} has llm_calls", (calls or 0) > 0, f"count={calls}")

        legacy = await db_scalar(f"SELECT COUNT(*) FROM executions WHERE mission_id = '{mid}'")
        section.check(
            f"P4:{label}", f"{label} zero legacy executions", legacy == 0, f"count={legacy}"
        )

    return section


# ---------------------------------------------------------------------------
# KNOWLEDGE — verify knowledge pipeline after execution
# ---------------------------------------------------------------------------


async def test_knowledge(
    token: str,
    mission_id: str,
    mission_name: str,
    verbose: bool,
) -> Section:
    """Verify knowledge endpoints work and Director can query learnings."""
    section = Section("KNOWLEDGE (post-execution)")

    # K1: Knowledge endpoint returns 200
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{API_BASE}/missions/{mission_id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
    section.check(
        "K1", "GET /knowledge returns 200", r.status_code == 200, f"status={r.status_code}"
    )

    # K2: Learnings endpoint returns list (may be empty on first run)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{API_BASE}/missions/{mission_id}/learnings",
            headers={"Authorization": f"Bearer {token}"},
        )
    learnings_data = r.json().get("data", [])
    learning_count = len(learnings_data) if isinstance(learnings_data, list) else 0
    section.check(
        "K2", "GET /learnings returns 200", r.status_code == 200, f"count={learning_count}"
    )

    # K3: Mission intent exists (seeded from --brief on creation)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{API_BASE}/missions/{mission_id}/intent",
            headers={"Authorization": f"Bearer {token}"},
        )
    intent_data = r.json().get("data")
    section.check("K3", "Mission intent exists", intent_data is not None and r.status_code == 200)

    # K4: Director can query knowledge via chat
    print("  Asking Director about learnings...")
    mc("mission", "use", mission_name)
    result = mc("chat", "What have you learned from the runs so far? Be brief.", "--new")
    got_response = result.returncode == 0 and len(result.stdout.strip()) > 20
    if verbose and result.stdout:
        for line in result.stdout.strip().split("\n")[-5:]:
            print(f"    {line}")
    section.check(
        "K4",
        "Director responds to knowledge query",
        got_response,
        f"exit={result.returncode}, len={len(result.stdout.strip())}",
    )

    # K5: Platform search endpoint works
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{API_BASE}/knowledge/search",
            params={"q": "structured logging async"},
            headers={"Authorization": f"Bearer {token}"},
        )
    section.check(
        "K5", "GET /knowledge/search returns 200", r.status_code == 200, f"status={r.status_code}"
    )

    return section


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(sections: list[Section]) -> int:
    total_pass = 0
    total_fail = 0

    print("\n" + "=" * 60)
    print("  E2E TEST BENCH REPORT")
    print("=" * 60)

    for section in sections:
        print(f"\n  {section.name}")
        print(f"  {'-' * len(section.name)}")
        for g in section.gates:
            icon = PASS_ICON if g.passed else FAIL_ICON
            detail = f"  ({g.detail})" if g.detail else ""
            print(f"    {icon}  [{g.id}] {g.name}{detail}")
        total_pass += section.pass_count
        total_fail += section.fail_count

    total = total_pass + total_fail
    print(f"\n  {'=' * 40}")
    print(f"  Score: {total_pass}/{total} passed, {total_fail} failed")

    if total_fail == 0:
        print(f"\n  {PASS_ICON} VERDICT: ALL GATES PASSED")
    else:
        print(f"\n  {FAIL_ICON} VERDICT: {total_fail} GATE(S) FAILED")

    print()
    return total_fail


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(
    verbose: bool,
    cli_only: bool,
    api_only: bool,
    reset: bool,
) -> int:
    need_cli = not api_only
    need_api = not cli_only

    print(f"=== Plan 62 E2E Test Bench ===")
    if need_cli:
        print(f"  CLI mission: {BENCH_CLI_MISSION}")
    if need_api:
        print(f"  API mission: {BENCH_API_MISSION}")
    print(f"  Budget:      ${BENCH_BUDGET_USD}")
    print(f"  Gate:        {BENCH_GATE_MODE}")
    print(f"  Agents:      {len(REQUIRED_AGENTS)} required")
    print()

    # Pre-flight
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:8100/health")
            health = r.json().get("status")
    except Exception:
        health = None

    if health != "healthy":
        print(f"ABORT: Backend not healthy (got: {health})")
        return 99

    token = await get_token()
    if not token:
        print("ABORT: Failed to get auth token")
        return 99

    print(f"  Backend:     healthy")
    print(f"  Auth:        token acquired\n")

    sections: list[Section] = []

    # SETUP — separate missions for CLI and API
    print("--- SETUP ---")
    setup_section, cli_id, api_id = await setup_bench(
        token,
        reset,
        verbose,
        need_cli,
        need_api,
    )
    sections.append(setup_section)
    if (need_cli and not cli_id) or (need_api and not api_id):
        print("\nABORT: Required mission(s) not available")
        return print_report(sections)
    print()

    # CLI path — own mission
    if need_cli and cli_id:
        print("--- CLI ---")
        sections.append(await test_cli(cli_id, verbose))
        print()

    # API path — own mission
    if need_api and api_id:
        print("--- API ---")
        sections.append(await test_api(token, api_id, verbose))
        print()

        print("--- LOOP ---")
        sections.append(await test_multiwave(token, api_id, verbose))
        print()

    # Parity — compare both missions
    if need_cli and need_api and cli_id and api_id:
        print("--- PARITY ---")
        sections.append(await test_parity(cli_id, api_id))
        print()

    # Knowledge — test against whichever mission ran
    knowledge_id = cli_id or api_id
    knowledge_name = BENCH_CLI_MISSION if cli_id else BENCH_API_MISSION
    if knowledge_id:
        print("--- KNOWLEDGE ---")
        sections.append(await test_knowledge(token, knowledge_id, knowledge_name, verbose))

    return print_report(sections)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plan 62 — E2E Test Bench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/verify_unified_execution.py              # all paths
  python scripts/verify_unified_execution.py --cli-only   # CLI only
  python scripts/verify_unified_execution.py --api-only   # API + loop only
  python scripts/verify_unified_execution.py --reset      # fresh start
  python scripts/verify_unified_execution.py --verbose    # show output
        """,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli-only", action="store_true", help="CLI path only")
    mode.add_argument("--api-only", action="store_true", help="API + loop only")
    parser.add_argument("--verbose", action="store_true", help="Show responses")
    parser.add_argument("--debug", action="store_true", help="DEBUG logging")
    parser.add_argument("--reset", action="store_true", help="Fresh mission")
    parser.add_argument("--timeout", type=int, default=180, help="Max idle wait (s)")
    args = parser.parse_args()

    if args.debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    exit_code = asyncio.run(
        main(
            verbose=args.verbose or args.debug,
            cli_only=args.cli_only,
            api_only=args.api_only,
            reset=args.reset,
        )
    )
    sys.exit(exit_code)
