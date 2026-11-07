#!/usr/bin/env python3
"""
Single-call Think Tank baseline (Plan 79 validation experiment).

Asks ONE Claude Opus 4.6 call (Copilot SDK, reasoning_effort=high) to
produce the same FinalDeliverable that v2's 7-agent deliberation does.
Used to test whether the multi-agent orchestration buys anything over a
single strong call.

Two modes:
  --packet PATH         load v2's research packet, skip web search.
                        Compares "single call vs v2 given the same research."
  (omit --packet)       enable search_web/fetch_url so the call does its
                        own research. Compares "single end-to-end call vs v2."

Usage:
  python scripts/think_tank_baseline.py \\
      --question "Will commercial fusion deliver utility-grade electricity by 2040?" \\
      --out outputs/baseline/q3_solo.json

  python scripts/think_tank_baseline.py \\
      --question "..." --packet artifacts/q3_v2_packet.json \\
      --out outputs/baseline/q3_with_packet.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
import httpx

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic_ai import Agent, UsageLimits  # noqa: E402

from modules.backend.agents.deps.base import FileScope  # noqa: E402
from modules.backend.agents.research.deps import ResearchAgentDeps  # noqa: E402
from modules.backend.core.copilot_model import CopilotModel  # noqa: E402
from modules.backend.core.logging import get_logger, setup_logging  # noqa: E402
from modules.backend.core.tls import configure_tls_trust  # noqa: E402
from modules.backend.schemas.deliberation import FinalDeliverable, ResearchPacket  # noqa: E402

logger = get_logger(__name__)


BASELINE_PROMPT = """\
You are producing a structured deliberation on a contested, open question.

This deliverable normally comes out of a 7-agent multi-round deliberation
(researcher -> 4 reasoning-diverse debaters -> critic over multiple rounds
-> synthesiser). For this run you are doing the whole thing in one pass
with extended thinking. Use the thinking budget to actually deliberate.
Do not collapse to a smooth surface answer.

Question: {question}

{packet_section}

Procedure (work through these in order, in your thinking budget):

1. Take 3 to 5 genuinely incompatible positions on the question. Not 3 to 5
   ways of phrasing the same answer -- 3 to 5 answers that could each be
   the right one, that competent observers would actually hold. For each,
   write the strongest version (steelman).

2. For each position, name its load-bearing assumption: the one specific
   claim that, if false, breaks the position. Then attack each of those
   assumptions. Do not be polite. Do not attack the weakest part of an
   argument -- attack the load-bearing one.

3. Identify the cruxes -- the specific disagreements between positions
   that the evidence cannot currently resolve. These go into
   FinalDeliverable.cruxes (minimum 2). They must be REAL disagreements
   (positions actually conflict), not "considerations" or "factors".

4. Identify a minority position worth preserving. If one of your positions
   survives the strongest attack but is not the most likely answer, that
   is the minority position. Name it. Explain why it survived. If none
   did, set minority_position to null -- but be honest: do not suppress a
   legitimate minority because it is inconvenient.

5. Audit against the mainstream consensus. State plainly what the
   conventional answer to this question would be. State whether your
   answer supports, modifies, rejects, or merely_reproduces it. The
   merely_reproduces enum value exists because "the deliberation just
   agreed with the mainstream view" is a documented failure mode you
   should explicitly check for.

6. Commit to a forward_claim with a horizon and explicit falsifiers.
   "It depends" is not an answer unless the dependencies are named.

7. List the 2 to 3 biggest_things_that_could_be_wrong -- the load-bearing
   claims that, if wrong, would invalidate your conclusion.

8. Write the full report_markdown rendering. It must include all
   sections: question restated, committed answer, each crux as its own
   subsection with steelmen, minority position if any, mainstream prior
   and how this answer related to it, forward claim with falsifiers,
   biggest things that could be wrong, sycophancy_flags if any. UK
   English. No em dashes.

Anti-sycophancy guidance: you are alone in this run. There is no peer
pressure to converge on. The failure mode is the opposite: you producing
a smooth, plausible, mainstream-aligned answer because that is what your
prior leans toward. Disagree with yourself across the lenses. Hold
positions that your prior would push you to drop.

Output format: structured JSON conforming to the FinalDeliverable schema.
"""


def _packet_section(packet: ResearchPacket | None) -> str:
    if packet is None:
        return (
            "You have web search tools (search_web, fetch_url) available. "
            "Use them to ground your claims. Do not fabricate sources -- "
            "if you cannot find a source for a claim, drop the claim or "
            "label it explicitly as a prior."
        )
    return (
        "Research packet (pre-assembled by a dedicated researcher in a "
        "previous step):\n\n"
        + json.dumps(packet.model_dump(), indent=2)
        + "\n\nWork from this packet. Do not invent sources beyond what "
        "is provided here."
    )


async def run_baseline(
    *,
    question: str,
    packet: ResearchPacket | None,
    reasoning_effort: str,
    request_limit: int,
) -> FinalDeliverable:
    model = CopilotModel(
        model_id="claude-opus-4.6",
        reasoning_effort=reasoning_effort,
    )

    agent = Agent(
        model,
        deps_type=ResearchAgentDeps,
        output_type=FinalDeliverable,
        instructions=(
            "You are a deliberation engine producing a single FinalDeliverable "
            "for a contested question. Follow the user prompt's procedure step "
            "by step in your thinking budget. Commit; do not hedge."
        ),
        output_retries=3,
    )

    if packet is None:
        from modules.backend.tools.registry import get_tool_registry

        registered = get_tool_registry().register_on_agent(
            agent,
            ["search_web", "fetch_url"],
        )
        logger.info("Registered tools", extra={"tools": registered})

    prompt = BASELINE_PROMPT.format(
        question=question,
        packet_section=_packet_section(packet),
    )

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        deps = ResearchAgentDeps(
            project_root=PROJECT_ROOT,
            scope=FileScope(read_paths=["*"], write_paths=[]),
            http_client=http_client,
        )
        result = await agent.run(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=request_limit),
        )
    return result.output


@click.command()
@click.option("--question", required=True, help="The contested question.")
@click.option(
    "--packet",
    "packet_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional: path to v2's ResearchPacket JSON. If omitted, the "
    "model uses search_web/fetch_url to do its own research.",
)
@click.option(
    "--out",
    "out_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path. The Markdown report is written as a sibling " "with .md extension.",
)
@click.option(
    "--reasoning-effort",
    default="high",
    type=click.Choice(["low", "medium", "high"]),
    help="Copilot reasoning effort. Default: high (we want extended thinking).",
)
@click.option(
    "--request-limit",
    default=40,
    type=int,
    help="Max tool-call/turn requests for the agent run. Higher when doing "
    "own research (more search calls).",
)
def main(
    question: str,
    packet_path: Path | None,
    out_path: Path,
    reasoning_effort: str,
    request_limit: int,
) -> None:
    setup_logging()
    configure_tls_trust()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    packet: ResearchPacket | None = None
    if packet_path is not None:
        packet = ResearchPacket.model_validate(json.loads(packet_path.read_text()))
        logger.info("Loaded research packet", extra={"path": str(packet_path)})

    mode = "with-packet" if packet else "solo-with-search"
    logger.info(
        "Running baseline",
        extra={
            "question": question[:100],
            "mode": mode,
            "reasoning_effort": reasoning_effort,
            "out": str(out_path),
        },
    )

    deliverable = asyncio.run(
        run_baseline(
            question=question,
            packet=packet,
            reasoning_effort=reasoning_effort,
            request_limit=request_limit,
        )
    )

    out_path.write_text(json.dumps(deliverable.model_dump(), indent=2))
    md_path = out_path.with_suffix(".md")
    md_path.write_text(deliverable.report_markdown)

    print(f"OK  json: {out_path}")
    print(f"OK   md : {md_path}")
    print(f"     confidence:           {deliverable.confidence}")
    print(f"     cruxes:               {len(deliverable.cruxes)}")
    print(f"     minority preserved:   {'yes' if deliverable.minority_position else 'no'}")
    print(f"     vs mainstream:        {deliverable.deliberation_vs_mainstream}")
    print(f"     sycophancy flags:     {len(deliverable.sycophancy_flags)}")


if __name__ == "__main__":
    main()
