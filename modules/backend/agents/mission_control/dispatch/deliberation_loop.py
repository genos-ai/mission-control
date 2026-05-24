"""Deliberation loop executor (Plan 79 v2).

Implements the Think Tank deliberation flow directly in Python rather
than as a 34-step wave-engine workflow. Mirrors the structural pattern
of `research_loop.py` — bypasses the Planning Agent's per-step
decomposition (which the v1 wave-engine workflow ran into repeatedly:
cost-estimate overshoots, request-limit retries, prompt drift, all
because Planning runs per agent_step).

Integration: called from dispatch/loop.py when a task has
`type=deliberation_loop` in its inputs.static.

Flow:
  1. Initial research      → researcher agent
  2. Verify packet         → verifier agent (loop up to N retries with feedback)
  3. Blind opening         → 4 debaters in parallel
  4. Critic round 0        → critic attacks all 4 positions
  5. Rounds 1..max_rounds  →
     a. Collect research_requests from previous round's debater outputs
     b. If any, dispatch researcher against each, append findings to packet
     c. 4 debaters in parallel with sparse-topology context
     d. Critic
     e. Early-stop check (deterministic stance-vector delta)
  6. Synthesise            → synthesiser produces FinalDeliverable
  7. Persist               → 3 artifacts (deliverable markdown, deliverable
                              JSON, transcript JSON) + learning entry
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import UsageLimits

from modules.backend.agents.mission_control.gate import GateReviewer, NoOpGate
from modules.backend.agents.mission_control.models import (
    EventBusProtocol,
    ExecuteAgentFn,
    NoOpEventBus,
)
from modules.backend.agents.mission_control.outcome import (
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
)
from modules.backend.core.logging import get_logger
from modules.backend.schemas.deliberation import (
    CriticReport,
    DebaterTurn,
    FinalDeliverable,
    ResearchPacket,
    ResearchPacketVerification,
    SourcedClaim,
)

logger = get_logger(__name__)


DEBATER_IDS = ("systems", "quant", "empiricist", "ethicist")


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class DeliberationConfig:
    """Configuration for a Think Tank deliberation."""

    max_rounds: int = 3
    agreement_intensity: float = 0.2
    early_stop_threshold: float = 0.15
    verifier_max_retries: int = 3

    # Agent names (overridable for tests)
    researcher_agent: str = "deliberation.researcher.agent"
    verifier_agent: str = "deliberation.research_verifier.agent"
    debater_agents: dict[str, str] = field(default_factory=lambda: {
        "systems": "deliberation.debater_systems.agent",
        "quant": "deliberation.debater_quant.agent",
        "empiricist": "deliberation.debater_empiricist.agent",
        "ethicist": "deliberation.debater_ethicist.agent",
    })
    critic_agent: str = "deliberation.critic.agent"
    synthesiser_agent: str = "deliberation.synthesiser.agent"

    # Per-call request limits (UsageLimits.request_limit)
    researcher_request_limit: int = 30
    verifier_request_limit: int = 5
    debater_request_limit: int = 10
    critic_request_limit: int = 10
    synthesiser_request_limit: int = 10

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliberationConfig:
        """Build from task input_data['loop_config']."""
        if not isinstance(data, dict):
            raise TypeError(f"loop_config must be a dict, got {type(data).__name__}")
        return cls(
            max_rounds=int(data.get("max_rounds", 3)),
            agreement_intensity=float(data.get("agreement_intensity", 0.2)),
            early_stop_threshold=float(data.get("early_stop_threshold", 0.15)),
            verifier_max_retries=int(data.get("verifier_max_retries", 3)),
        )


# =============================================================================
# Main executor
# =============================================================================


async def execute_deliberation_loop(
    *,
    task_id: str,
    question: str,
    config: DeliberationConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> TaskResult:
    """Execute a Think Tank deliberation."""
    logger.info(
        "TRACE >>> execute_deliberation_loop entered",
        extra={
            "task_id": task_id,
            "question": question[:80],
            "max_rounds": config.max_rounds,
            "session_id": session_id,
        },
    )
    _gate = gate or NoOpGate()
    _bus = event_bus or NoOpEventBus()
    _sid = session_id or ""
    start_time = time.monotonic()

    total_cost = 0.0
    total_tokens = TaskTokenUsage()

    # Imported lazily to avoid circular imports
    from modules.backend.agents.mission_control.helpers import _emit
    from modules.backend.events.types import MissionNarrativeEvent

    async def _narrative(phase: str, message: str) -> None:
        await _emit(
            _bus, MissionNarrativeEvent,
            session_id=_sid,
            source=f"deliberation:{task_id}",
            mission_id=mission_id,
            agent_id="deliberation",
            narrative=message,
            phase=phase,
            level="info",
        )

    try:
        # ── Phase 1: Initial research ────────────────────────────────
        await _narrative("research", f"Starting deliberation: \"{question}\"")
        await _narrative("research", "Assembling research packet...")

        packet, cost, tokens = await _run_researcher(
            agent=config.researcher_agent,
            execute_agent_fn=execute_agent_fn,
            question=question,
            previous_packet=None,
            feedback=None,
            request_limit=config.researcher_request_limit,
        )
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 2: Verify (retry-with-feedback up to N times) ──────
        await _narrative("verify", "Auditing the research packet...")
        verification: ResearchPacketVerification | None = None
        for attempt in range(1, config.verifier_max_retries + 1):
            verification, cost, tokens = await _run_verifier(
                agent=config.verifier_agent,
                execute_agent_fn=execute_agent_fn,
                packet=packet,
                request_limit=config.verifier_request_limit,
            )
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

            if verification.passed:
                await _narrative("verify", "Research packet passed verification.")
                break

            if attempt >= config.verifier_max_retries:
                msg = (
                    f"Research packet failed verification after "
                    f"{config.verifier_max_retries} attempts: "
                    f"{verification.issues_text}"
                )
                await _narrative("error", msg)
                return _failed_result(
                    task_id, msg, total_cost, total_tokens, start_time,
                )

            # Feedback loop — re-run researcher with the verifier's issues
            await _narrative(
                "research",
                f"Retrying research with verifier feedback (attempt {attempt + 1})...",
            )
            packet, cost, tokens = await _run_researcher(
                agent=config.researcher_agent,
                execute_agent_fn=execute_agent_fn,
                question=question,
                previous_packet=packet,
                feedback=verification.issues_text,
                request_limit=config.researcher_request_limit,
            )
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 3: Blind opening (4 parallel debaters) ─────────────
        await _narrative("debate", "Blind opening — four debaters take initial positions.")
        opens_pairs = await asyncio.gather(*[
            _run_debater(
                agent=config.debater_agents[d],
                execute_agent_fn=execute_agent_fn,
                debater_id=d,
                question=question,
                packet=packet,
                round_index=0,
                agreement_intensity=config.agreement_intensity,
                own_previous=None,
                opponents_previous=None,
                critic_attack_on_self=None,
                request_limit=config.debater_request_limit,
            )
            for d in DEBATER_IDS
        ])
        # Each pair is (DebaterTurn, cost, tokens)
        rounds: dict[int, dict[str, DebaterTurn]] = {0: {}}
        for d, (turn, cost, tokens) in zip(DEBATER_IDS, opens_pairs, strict=True):
            rounds[0][d] = turn
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 4: Critic round 0 ──────────────────────────────────
        await _narrative("critic", "Critic attacks each debater's opening.")
        critics: dict[int, CriticReport] = {}
        critic_r0, cost, tokens = await _run_critic(
            agent=config.critic_agent,
            execute_agent_fn=execute_agent_fn,
            question=question,
            packet=packet,
            positions=rounds[0],
            round_index=0,
            request_limit=config.critic_request_limit,
        )
        critics[0] = critic_r0
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 5: Rounds 1..max_rounds with optional follow-up research ─
        stance_deltas: dict[int, dict[str, Any]] = {}
        last_completed_round = 0

        for round_idx in range(1, config.max_rounds + 1):
            # Pool research_requests from the previous round's debater outputs
            requests = _collect_research_requests(rounds[round_idx - 1])
            if requests:
                await _narrative(
                    "research",
                    f"Round {round_idx}: debaters requested {len(requests)} follow-up "
                    f"research item(s). Dispatching researcher...",
                )
                for req in requests:
                    new_claims, cost, tokens = await _follow_up_research(
                        agent=config.researcher_agent,
                        execute_agent_fn=execute_agent_fn,
                        question=req,
                        request_limit=config.researcher_request_limit,
                    )
                    total_cost += cost
                    total_tokens = _accumulate(total_tokens, tokens)
                    packet = _merge_findings(packet, new_claims)

            # Run 4 debaters in parallel with sparse topology
            await _narrative("debate", f"Round {round_idx}: four debaters respond.")
            round_n_pairs = await asyncio.gather(*[
                _run_debater(
                    agent=config.debater_agents[d],
                    execute_agent_fn=execute_agent_fn,
                    debater_id=d,
                    question=question,
                    packet=packet,
                    round_index=round_idx,
                    agreement_intensity=config.agreement_intensity,
                    own_previous=rounds[round_idx - 1][d],
                    opponents_previous={
                        other: rounds[round_idx - 1][other]
                        for other in DEBATER_IDS if other != d
                    },
                    critic_attack_on_self=critics[round_idx - 1].attacks.get(d),
                    request_limit=config.debater_request_limit,
                )
                for d in DEBATER_IDS
            ])
            rounds[round_idx] = {}
            for d, (turn, cost, tokens) in zip(DEBATER_IDS, round_n_pairs, strict=True):
                rounds[round_idx][d] = turn
                total_cost += cost
                total_tokens = _accumulate(total_tokens, tokens)

            # Critic for this round
            await _narrative("critic", f"Critic attacks round {round_idx} positions.")
            critic_n, cost, tokens = await _run_critic(
                agent=config.critic_agent,
                execute_agent_fn=execute_agent_fn,
                question=question,
                packet=packet,
                positions=rounds[round_idx],
                round_index=round_idx,
                request_limit=config.critic_request_limit,
            )
            critics[round_idx] = critic_n
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)
            last_completed_round = round_idx

            # Early-stop check (deterministic, no LLM)
            from modules.backend.tools.compute_stance_delta import (
                compute_stance_delta,
            )

            delta = await compute_stance_delta(
                previous_round={d: rounds[round_idx - 1][d].model_dump() for d in DEBATER_IDS},
                current_round={d: rounds[round_idx][d].model_dump() for d in DEBATER_IDS},
                threshold=config.early_stop_threshold,
            )
            stance_deltas[round_idx] = delta
            if not delta["should_continue"]:
                await _narrative(
                    "early_stop",
                    f"Stance stable after round {round_idx} "
                    f"(delta={delta['delta']:.3f} < threshold). Skipping further rounds.",
                )
                break

        # ── Phase 6: Synthesise ──────────────────────────────────────
        await _narrative("synthesise", "Synthesising the final deliverable.")
        deliverable, cost, tokens = await _run_synthesiser(
            agent=config.synthesiser_agent,
            execute_agent_fn=execute_agent_fn,
            question=question,
            packet=packet,
            rounds=rounds,
            critic_reports=critics,
            stance_deltas=stance_deltas,
            request_limit=config.synthesiser_request_limit,
        )
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 7: Persist artifacts ───────────────────────────────
        if mission_id:
            await _persist_artifacts(
                mission_id=mission_id,
                question=question,
                packet=packet,
                rounds=rounds,
                critics=critics,
                stance_deltas=stance_deltas,
                deliverable=deliverable,
            )

        await _narrative("done", "Deliberation complete.")
        return TaskResult(
            task_id=task_id,
            agent_name="deliberation",
            status=TaskStatus.SUCCESS,
            output_reference=deliverable.model_dump(),
            cost_usd=total_cost,
            token_usage=total_tokens,
            duration_seconds=round(time.monotonic() - start_time, 2),
        )

    except Exception as exc:
        logger.exception(
            "Deliberation loop failed",
            extra={"task_id": task_id, "mission_id": mission_id},
        )
        return _failed_result(
            task_id, f"Deliberation loop error: {exc}",
            total_cost, total_tokens, start_time,
        )


# =============================================================================
# Phase helpers — each returns (output_model, cost_usd, tokens)
# =============================================================================


async def _run_researcher(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    previous_packet: ResearchPacket | None,
    feedback: str | None,
    request_limit: int,
) -> tuple[ResearchPacket, float, TaskTokenUsage]:
    instructions = f"Research this contested question: {question}"
    inputs: dict[str, Any] = {"question": question}
    if feedback:
        instructions += (
            f"\n\nThe verifier rejected the previous packet with these "
            f"issues:\n{feedback}\n\nProduce a new packet that addresses "
            f"every issue. Drop unverifiable claims; only include claims "
            f"you have confirmed via search_web/fetch_url tool calls."
        )
        inputs["previous_packet_issues"] = feedback

    result = await execute_agent_fn(
        agent_name=agent,
        instructions=instructions,
        inputs=inputs,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, ResearchPacket)
    if output is None:
        raise RuntimeError("Researcher returned no valid ResearchPacket")
    return output, _cost(result), _tokens(result)


async def _follow_up_research(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    request_limit: int,
) -> tuple[list[SourcedClaim], float, TaskTokenUsage]:
    """A targeted researcher call that returns only the new claims.

    The full ResearchPacket schema isn't ideal for "answer this one
    question" — but it's what the researcher knows how to produce.
    We take just the new what_is_known claims and merge them into
    the running packet.
    """
    instructions = (
        f"A debater has requested follow-up research on a specific point. "
        f"Produce a focused mini-packet (3-5 sourced claims minimum) answering: "
        f"{question}\n\n"
        f"You may produce a minimal packet — only the `what_is_known` claims "
        f"matter for this call. Keep `expert_disagreements` and "
        f"`under_discussed_angles` short. Use search_web and fetch_url; do "
        f"not fabricate sources."
    )
    result = await execute_agent_fn(
        agent_name=agent,
        instructions=instructions,
        inputs={"question": question, "mode": "follow_up"},
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, ResearchPacket)
    new_claims = list(output.what_is_known) if output else []
    return new_claims, _cost(result), _tokens(result)


async def _run_verifier(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    packet: ResearchPacket,
    request_limit: int,
) -> tuple[ResearchPacketVerification, float, TaskTokenUsage]:
    result = await execute_agent_fn(
        agent_name=agent,
        instructions="Audit this research packet.",
        inputs={"packet": packet.model_dump()},
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, ResearchPacketVerification)
    if output is None:
        raise RuntimeError("Verifier returned no valid output")
    return output, _cost(result), _tokens(result)


async def _run_debater(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    debater_id: str,
    question: str,
    packet: ResearchPacket,
    round_index: int,
    agreement_intensity: float,
    own_previous: DebaterTurn | None,
    opponents_previous: dict[str, DebaterTurn] | None,
    critic_attack_on_self: Any | None,
    request_limit: int,
) -> tuple[DebaterTurn, float, TaskTokenUsage]:
    inputs: dict[str, Any] = {
        "question": question,
        "research_packet": packet.model_dump(),
        "round_index": round_index,
        "agreement_intensity": agreement_intensity,
    }
    if own_previous is not None:
        inputs["own_previous"] = own_previous.model_dump()
    if opponents_previous:
        inputs["opponents_previous"] = {
            k: v.model_dump() for k, v in opponents_previous.items()
        }
    if critic_attack_on_self is not None:
        inputs["critic_attack_on_self"] = (
            critic_attack_on_self.model_dump()
            if hasattr(critic_attack_on_self, "model_dump")
            else critic_attack_on_self
        )

    label = "blind opening" if round_index == 0 else f"round {round_index} response"
    instructions = (
        f"{label.capitalize()}. Question: {question}. "
        f"You are the {debater_id} debater."
    )
    result = await execute_agent_fn(
        agent_name=agent,
        instructions=instructions,
        inputs=inputs,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, DebaterTurn)
    if output is None:
        raise RuntimeError(f"Debater {debater_id} returned no valid output")
    return output, _cost(result), _tokens(result)


async def _run_critic(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    packet: ResearchPacket,
    positions: dict[str, DebaterTurn],
    round_index: int,
    request_limit: int,
) -> tuple[CriticReport, float, TaskTokenUsage]:
    inputs = {
        "question": question,
        "research_packet": packet.model_dump(),
        "round_index": round_index,
        "positions": {d: t.model_dump() for d, t in positions.items()},
    }
    result = await execute_agent_fn(
        agent_name=agent,
        instructions=f"Critique the round {round_index} positions.",
        inputs=inputs,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, CriticReport)
    if output is None:
        raise RuntimeError("Critic returned no valid output")
    return output, _cost(result), _tokens(result)


async def _run_synthesiser(
    *,
    agent: str,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    packet: ResearchPacket,
    rounds: dict[int, dict[str, DebaterTurn]],
    critic_reports: dict[int, CriticReport],
    stance_deltas: dict[int, dict[str, Any]],
    request_limit: int,
) -> tuple[FinalDeliverable, float, TaskTokenUsage]:
    all_rounds_dict = {
        f"round_{idx}": {d: t.model_dump() for d, t in turns.items()}
        for idx, turns in rounds.items()
    }
    critics_dict = {f"round_{idx}": r.model_dump() for idx, r in critic_reports.items()}
    inputs = {
        "question": question,
        "research_packet": packet.model_dump(),
        "mainstream_consensus": packet.mainstream_consensus,
        "all_rounds": all_rounds_dict,
        "critic_reports": critics_dict,
        "stance_deltas": stance_deltas,
    }
    result = await execute_agent_fn(
        agent_name=agent,
        instructions="Synthesise the final deliverable from the deliberation transcript.",
        inputs=inputs,
        usage_limits=UsageLimits(request_limit=request_limit),
    )
    output = _parse_output(result, FinalDeliverable)
    if output is None:
        raise RuntimeError("Synthesiser returned no valid output")
    return output, _cost(result), _tokens(result)


# =============================================================================
# Persistence
# =============================================================================


async def _persist_artifacts(
    *,
    mission_id: str,
    question: str,
    packet: ResearchPacket,
    rounds: dict[int, dict[str, DebaterTurn]],
    critics: dict[int, CriticReport],
    stance_deltas: dict[int, dict[str, Any]],
    deliverable: FinalDeliverable,
) -> None:
    """Three artifacts + a learning entry. Best-effort — logs and continues on error."""
    from modules.backend.tools.store_artifact import store_artifact
    from modules.backend.tools.store_learning import store_learning

    try:
        await store_artifact(
            mission_id=mission_id,
            title=f"Think Tank Deliverable: {question}"[:200],
            content=deliverable.report_markdown,
            artifact_type="deliberation_deliverable",
            content_type="markdown",
        )
    except Exception:
        logger.warning("store-deliverable-markdown failed", exc_info=True)

    try:
        await store_artifact(
            mission_id=mission_id,
            title=f"Think Tank Deliverable (structured): {question}"[:200],
            content=deliverable.model_dump(),
            artifact_type="deliberation_deliverable",
            content_type="json",
        )
    except Exception:
        logger.warning("store-deliverable-json failed", exc_info=True)

    try:
        transcript = {
            "question": question,
            "research_packet": packet.model_dump(),
            "rounds": {
                f"round_{idx}": {d: t.model_dump() for d, t in turns.items()}
                for idx, turns in rounds.items()
            },
            "critic_reports": {
                f"round_{idx}": r.model_dump() for idx, r in critics.items()
            },
            "stance_deltas": {
                f"after_round_{idx}": delta for idx, delta in stance_deltas.items()
            },
        }
        await store_artifact(
            mission_id=mission_id,
            title=f"Think Tank Transcript: {question}"[:200],
            content=transcript,
            artifact_type="deliberation_transcript",
            content_type="json",
        )
    except Exception:
        logger.warning("store-transcript failed", exc_info=True)

    try:
        await store_learning(
            mission_id=mission_id,
            title=f"Deliberation cruxes: {question}"[:200],
            body=deliverable.report_markdown,
            recommendation=deliverable.recommendation_markdown,
            kind="deliberation",
            domain_tags=["deliberation", "cruxes"],
            confidence=deliverable.confidence,
        )
    except Exception:
        logger.warning("store-learning failed", exc_info=True)


# =============================================================================
# Utilities
# =============================================================================


def _collect_research_requests(turns: dict[str, DebaterTurn]) -> list[str]:
    """Pool research_requests from a round's debater outputs.

    Deduplicates within the round (case-insensitive normalised). No
    cross-round dedupe — a debater might re-ask if previous research
    was inadequate.
    """
    seen: set[str] = set()
    pooled: list[str] = []
    for turn in turns.values():
        for req in turn.research_requests:
            key = req.strip().lower()
            if key and key not in seen:
                seen.add(key)
                pooled.append(req.strip())
    return pooled


def _merge_findings(
    packet: ResearchPacket, new_claims: list[SourcedClaim],
) -> ResearchPacket:
    """Append new claims to packet.what_is_known.

    Returns a NEW packet so callers can keep the original for the
    transcript if they need it. In this executor we just reassign.
    """
    if not new_claims:
        return packet
    merged = list(packet.what_is_known) + list(new_claims)
    return packet.model_copy(update={"what_is_known": merged})


def _parse_output(result: dict, schema_cls):
    """Extract the agent's structured output and validate against the schema."""
    payload = result.get("output", result)
    if isinstance(payload, schema_cls):
        return payload
    if isinstance(payload, dict):
        try:
            return schema_cls.model_validate(payload)
        except Exception:
            logger.warning(
                "Failed to validate agent output",
                extra={"schema": schema_cls.__name__},
                exc_info=True,
            )
            return None
    return None


def _cost(result: dict) -> float:
    return float((result.get("_meta") or {}).get("cost_usd") or 0.0)


def _tokens(result: dict) -> TaskTokenUsage:
    meta = result.get("_meta") or {}
    return TaskTokenUsage(
        input=int(meta.get("input_tokens") or 0),
        output=int(meta.get("output_tokens") or 0),
        thinking=int(meta.get("thinking_tokens") or 0),
    )


def _accumulate(total: TaskTokenUsage, add: TaskTokenUsage) -> TaskTokenUsage:
    return TaskTokenUsage(
        input=total.input + add.input,
        output=total.output + add.output,
        thinking=total.thinking + add.thinking,
    )


def _failed_result(
    task_id: str,
    reason: str,
    cost: float,
    tokens: TaskTokenUsage,
    start_time: float,
) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent_name="deliberation",
        status=TaskStatus.FAILED,
        output_reference={"error": reason},
        cost_usd=cost,
        token_usage=tokens,
        duration_seconds=round(time.monotonic() - start_time, 2),
    )
