#!/usr/bin/env python3
"""
Direct v2 deliberation invocation (Plan 79 validation experiment).

Bypasses the FastAPI/CLI/Temporal stack and calls
execute_deliberation_loop() directly in-process. Same execution path
as the workflow YAML, but no HTTP transport timeouts and full
visibility into per-phase failures.

Useful when:
  - The CLI keeps timing out (httpx ReadTimeout) because the synchronous
    POST endpoint blocks for the 30-45 min the workflow takes.
  - You want to capture the deliverable to a known file path for a
    blinded A/B comparison.

Usage:
  python scripts/think_tank_v2.py \\
      --question "..." \\
      --out var/validation/v2/q1.json

The deliverable JSON is written to --out; the report_markdown is
written to the .md sibling. Persistence to the mission's artifact
store is skipped (mission_id=None).
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.backend.agents.mission_control.dispatch.deliberation_loop import (
    DeliberationConfig,
    execute_deliberation_loop,
)
from modules.backend.agents.mission_control.gate import NoOpGate
from modules.backend.agents.mission_control.helpers.agent_executor import (
    _make_agent_executor,
)
from modules.backend.agents.mission_control.models import NoOpEventBus
from modules.backend.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


async def run_v2(
    *,
    question: str,
    max_rounds: int,
    agreement_intensity: float,
    early_stop_threshold: float,
    verifier_max_retries: int,
) -> dict:
    session_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    event_bus = NoOpEventBus()
    gate = NoOpGate()

    execute_agent_fn = _make_agent_executor(
        event_bus,
        session_id=session_id,
        mission_id="",
        environment_handle=None,
        current_user_id=None,
    )

    config = DeliberationConfig(
        max_rounds=max_rounds,
        agreement_intensity=agreement_intensity,
        early_stop_threshold=early_stop_threshold,
        verifier_max_retries=verifier_max_retries,
    )

    logger.info(
        "Starting direct v2 deliberation",
        extra={
            "session_id": session_id,
            "task_id": task_id,
            "question": question[:100],
            "max_rounds": max_rounds,
        },
    )

    result = await execute_deliberation_loop(
        task_id=task_id,
        question=question,
        config=config,
        execute_agent_fn=execute_agent_fn,
        mission_id=None,
        gate=gate,
        event_bus=event_bus,
        session_id=session_id,
    )

    return {
        "status": str(result.status),
        "duration_seconds": result.duration_seconds,
        "cost_usd": result.cost_usd,
        "output": result.output_reference,
    }


@click.command()
@click.option("--question", required=True, help="The contested question.")
@click.option(
    "--out", "out_path", required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path. .md sibling written automatically.",
)
@click.option("--max-rounds", default=3, type=int)
@click.option("--agreement-intensity", default=0.2, type=float)
@click.option("--early-stop-threshold", default=0.15, type=float)
@click.option("--verifier-max-retries", default=3, type=int)
def main(
    question: str,
    out_path: Path,
    max_rounds: int,
    agreement_intensity: float,
    early_stop_threshold: float,
    verifier_max_retries: int,
) -> None:
    setup_logging()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(run_v2(
        question=question,
        max_rounds=max_rounds,
        agreement_intensity=agreement_intensity,
        early_stop_threshold=early_stop_threshold,
        verifier_max_retries=verifier_max_retries,
    ))

    out_path.write_text(json.dumps(result, indent=2, default=str))

    output = result.get("output") or {}
    if isinstance(output, dict) and output.get("report_markdown"):
        md_path = out_path.with_suffix(".md")
        md_path.write_text(output["report_markdown"])
        print(f"OK  json: {out_path}")
        print(f"OK   md : {md_path}")
    else:
        print(f"OK  json: {out_path}")
        print("WARN no report_markdown in output; .md not written")

    print(f"     status:               {result.get('status')}")
    print(f"     cost_usd:             {result.get('cost_usd'):.4f}")
    print(f"     duration_seconds:     {result.get('duration_seconds')}")
    if isinstance(output, dict):
        print(f"     confidence:           {output.get('confidence')}")
        cruxes = output.get("cruxes") or []
        print(f"     cruxes:               {len(cruxes)}")
        print(f"     minority preserved:   {'yes' if output.get('minority_position') else 'no'}")
        print(f"     vs mainstream:        {output.get('deliberation_vs_mainstream')}")
        sflags = output.get("sycophancy_flags") or []
        print(f"     sycophancy flags:     {len(sflags)}")
    if "error" in (output if isinstance(output, dict) else {}):
        print(f"     ERROR:                {output['error']}")


if __name__ == "__main__":
    main()
