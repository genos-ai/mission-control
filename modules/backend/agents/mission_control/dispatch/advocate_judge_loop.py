"""Advocate-Judge deliberation executor (Plan 80 Phase 1 skeleton).

Implements the Think Tank Advocate-Judge flow as a Python executor,
mirroring the pattern of `deliberation_loop.py` (v2) and
`research_loop.py` (Plan 40). Bypasses the wave engine's per-step
Planning Agent overhead by running all 11-14 agent calls inside a
single `type: advocate_judge_loop` workflow step.

Integration: routed from `dispatch/loop.py` when a task has
`type=advocate_judge_loop` in its inputs.static (the dispatch-loop
fork lands in Phase 6).

Flow:
  Phase 1 — framer + framings validator -> final CandidateSet
  Phase 2 — N asymmetric side researchers (parallel) -> list[SidePacket]
  Phase 3 — N blind advocates (parallel) -> list[AdvocateCase]
  Phase 4 — N attackers seeing all packets + cases (parallel)
            -> list[AttacksByAdvocate]
  Phase 5 — judge -> FinalDeliverable
  Phase 6 — persistence (mission-attached runs only)

Per-side model assignment (Plan 80 §5.1): each per-side researcher +
advocate pair gets a different model family (Claude / GPT / Gemini)
so the system has two structural anti-convergence mechanisms:
(a) information asymmetry between sides (different evidence per side);
(b) model-family heterogeneity per side (different priors per side).

This Phase-1 file is a skeleton: it calls `execute_agent_fn` with the
right inputs in the right topology, but per-side model override
plumbing is documented (via `_resolved_model` in the inputs dict) and
wired through to be activated in Phase 6 when execute_agent_fn learns
to honour it. Tests verify the topology and the input shapes without
needing real agents to be registered.
"""

from __future__ import annotations

import asyncio
import time

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
from modules.backend.schemas.deliberation import FinalDeliverable
from modules.backend.schemas.deliberation_advocate_judge import (
    AdvocateCase,
    AdvocateJudgeConfig,
    AttacksByAdvocate,
    CandidateAnswer,
    CandidateSet,
    FramingValidation,
    SidePacket,
)

logger = get_logger(__name__)


# =============================================================================
# Per-side model rotation
# =============================================================================


# Listed in preference order. The executor walks this list, dropping any
# model whose provider isn't wired, and uses what's left to assign one
# model per side. If fewer entries remain than there are sides, families
# repeat (with a sycophancy_flags note added at synthesis time).
DEFAULT_SIDE_MODEL_ROTATION: tuple[str, ...] = (
    "copilot:claude-opus-4.6",
    "copilot:gpt-5.5",
    "google:gemini-2.5-pro",
    "copilot:claude-sonnet-4.6",
)


def _resolve_side_models(
    *,
    n_sides: int,
    explicit: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Resolve the per-side model list and a list of advisory notes.

    Returns (resolved_models, notes). The list has exactly `n_sides`
    entries. Notes are strings to be surfaced as `sycophancy_flags`
    entries on the final deliverable when heterogeneity is reduced.

    Resolution policy:
    - If `explicit` provided, validate length / prune unknown providers
      via `_build_model`; raise if fewer than 1 model survives.
    - Otherwise, walk DEFAULT_SIDE_MODEL_ROTATION, dropping unsupported
      providers, until we have `n_sides` or run out.
    - If fewer entries survive than `n_sides`, repeat from the start —
      add an advisory note that heterogeneity is reduced.
    """
    notes: list[str] = []
    candidates = list(explicit) if explicit else list(DEFAULT_SIDE_MODEL_ROTATION)
    wired = [m for m in candidates if _provider_is_wired(m)]
    if not wired:
        raise ValueError(
            f"No usable models in {candidates!r}. At least one provider must be wired.",
        )
    dropped = [m for m in candidates if m not in wired]
    if dropped:
        notes.append(
            "Dropped unsupported per-side models (provider not wired): "
            f"{dropped!r}. See _build_model in model_builder.py.",
        )
    resolved: list[str] = []
    while len(resolved) < n_sides:
        for m in wired:
            if len(resolved) >= n_sides:
                break
            resolved.append(m)
    if len(set(resolved)) < n_sides:
        notes.append(
            f"Per-side model rotation has {len(set(resolved))} distinct "
            f"families across {n_sides} sides — some sides share a model "
            "family. Heterogeneity is reduced.",
        )
    return resolved, notes


def _provider_is_wired(model_name: str) -> bool:
    """True if `_build_model` can construct this model.

    Uses the live `_build_model` helper as the source of truth — any
    new provider added there is automatically picked up.
    """
    from modules.backend.core.model_builder import _build_model
    try:
        _build_model(model_name)
    except Exception:
        return False
    return True


def _validate_judge_model(judge_model: str) -> None:
    """Raise if the judge model's provider isn't wired."""
    if not _provider_is_wired(judge_model):
        raise ValueError(
            f"Judge model {judge_model!r} provider is not wired in "
            "modules/backend/core/model_builder.py. Add the branch or "
            "override AdvocateJudgeConfig.judge_model.",
        )


# =============================================================================
# Main executor
# =============================================================================


async def execute_advocate_judge_loop(
    *,
    task_id: str,
    question: str,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> TaskResult:
    """Execute an Advocate-Judge deliberation.

    Mission-attached runs (mission_id set) persist artifacts at the end.
    Ad-hoc runs (mission_id=None) skip persistence; the caller reads the
    FinalDeliverable from TaskResult.output_reference.
    """
    logger.info(
        "TRACE >>> execute_advocate_judge_loop entered",
        extra={
            "task_id": task_id,
            "question": question[:80],
            "min_candidates": config.min_candidates,
            "max_candidates": config.max_candidates,
            "session_id": session_id,
        },
    )
    _gate = gate or NoOpGate()
    _bus = event_bus or NoOpEventBus()
    _sid = session_id or ""
    start_time = time.monotonic()

    total_cost = 0.0
    total_tokens = TaskTokenUsage()
    advisory_notes: list[str] = []

    from modules.backend.agents.mission_control.helpers import _emit
    from modules.backend.events.types import MissionNarrativeEvent

    async def _narrative(phase: str, message: str) -> None:
        await _emit(
            _bus, MissionNarrativeEvent,
            session_id=_sid,
            source=f"advocate_judge:{task_id}",
            mission_id=mission_id,
            agent_id="advocate_judge",
            narrative=message,
            phase=phase,
            level="info",
        )

    try:
        # ── Phase 0: validate judge model (fail loud at start) ────────
        _validate_judge_model(config.judge_model)

        # ── Phase 1: framing ──────────────────────────────────────────
        await _narrative("framing", f"Starting Advocate-Judge deliberation: \"{question}\"")
        await _narrative("framing", "Framer is decomposing the question into candidate answers...")

        framer_set, cost, tokens = await _run_framer(
            config=config,
            execute_agent_fn=execute_agent_fn,
            question=question,
        )
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        await _narrative("validate_framing", "Framings validator is auditing the candidate set...")
        validation, cost, tokens = await _run_framings_validator(
            config=config,
            execute_agent_fn=execute_agent_fn,
            question=question,
            framer_set=framer_set,
        )
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        candidate_set = validation.revised_set if validation.verdict == "revised" else framer_set
        if validation.verdict == "revised":
            advisory_notes.append(
                f"Framings validator revised the candidate set: {validation.rationale[:200]}",
            )

        # ── Resolve per-side models now that N is known ───────────────
        n_sides = len(candidate_set.candidates)
        side_models, rotation_notes = _resolve_side_models(
            n_sides=n_sides,
            explicit=config.side_models,
        )
        advisory_notes.extend(rotation_notes)
        await _narrative(
            "framing",
            f"Framing settled on {n_sides} candidates: "
            f"{[c.label for c in candidate_set.candidates]}. "
            f"Per-side models: {side_models}.",
        )

        # ── Phase 2: asymmetric research (parallel) ───────────────────
        await _narrative("research", f"{n_sides} per-side researchers running in parallel...")
        packets_pairs = await asyncio.gather(*[
            _run_side_researcher(
                config=config,
                execute_agent_fn=execute_agent_fn,
                question=question,
                candidate=c,
                model=side_models[i],
            )
            for i, c in enumerate(candidate_set.candidates)
        ])
        packets: list[SidePacket] = []
        for packet, cost, tokens in packets_pairs:
            packets.append(packet)
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 3: blind advocates (parallel) ───────────────────────
        await _narrative("advocacy", f"{n_sides} blind advocate cases in parallel...")
        cases_pairs = await asyncio.gather(*[
            _run_advocate_blind(
                config=config,
                execute_agent_fn=execute_agent_fn,
                question=question,
                candidate=c,
                own_packet=packets[i],
                model=side_models[i],
            )
            for i, c in enumerate(candidate_set.candidates)
        ])
        cases: list[AdvocateCase] = []
        for case, cost, tokens in cases_pairs:
            cases.append(case)
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 4: bilateral attacks (parallel) ─────────────────────
        await _narrative("attacks", f"{n_sides} attackers each attacking {n_sides - 1} others...")
        attacks_pairs = await asyncio.gather(*[
            _run_advocate_attacks(
                config=config,
                execute_agent_fn=execute_agent_fn,
                question=question,
                candidate=c,
                own_case=cases[i],
                all_cases=cases,
                all_packets=packets,
                model=side_models[i],
            )
            for i, c in enumerate(candidate_set.candidates)
        ])
        attacks: list[AttacksByAdvocate] = []
        for atk, cost, tokens in attacks_pairs:
            attacks.append(atk)
            total_cost += cost
            total_tokens = _accumulate(total_tokens, tokens)

        # ── Phase 5: judge ────────────────────────────────────────────
        await _narrative("judge", "Judge reads everything and produces the deliverable...")
        deliverable, cost, tokens = await _run_judge(
            config=config,
            execute_agent_fn=execute_agent_fn,
            question=question,
            candidate_set=candidate_set,
            packets=packets,
            cases=cases,
            attacks=attacks,
        )
        total_cost += cost
        total_tokens = _accumulate(total_tokens, tokens)

        # Surface advisory notes as sycophancy_flags so they reach the
        # persisted deliverable (the judge can't know about
        # heterogeneity-reduction; only the executor can).
        if advisory_notes:
            merged_flags = list(deliverable.sycophancy_flags) + advisory_notes
            deliverable = deliverable.model_copy(update={"sycophancy_flags": merged_flags})

        # ── Phase 6: persistence ──────────────────────────────────────
        if mission_id:
            await _persist_artifacts(
                mission_id=mission_id,
                question=question,
                candidate_set=candidate_set,
                packets=packets,
                cases=cases,
                attacks=attacks,
                deliverable=deliverable,
                side_models=side_models,
            )

        await _narrative("done", "Advocate-Judge deliberation complete.")
        return TaskResult(
            task_id=task_id,
            agent_name="advocate_judge",
            status=TaskStatus.SUCCESS,
            output_reference=deliverable.model_dump(),
            cost_usd=total_cost,
            token_usage=total_tokens,
            duration_seconds=round(time.monotonic() - start_time, 2),
        )

    except Exception as exc:
        logger.exception(
            "Advocate-Judge loop failed",
            extra={"task_id": task_id, "mission_id": mission_id},
        )
        return _failed_result(
            task_id, f"Advocate-Judge loop error: {exc}",
            total_cost, total_tokens, start_time,
        )


# =============================================================================
# Phase helpers — each returns (output_model, cost_usd, tokens)
# =============================================================================


async def _run_framer(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
) -> tuple[CandidateSet, float, TaskTokenUsage]:
    result = await execute_agent_fn(
        agent_name=config.framer_agent,
        instructions=(
            f"Decompose this contested question into the live answer space: "
            f"{question}. Produce {config.min_candidates} to "
            f"{config.max_candidates} candidate answers and the mainstream "
            "consensus. See your system prompt for the full procedure."
        ),
        inputs={
            "question": question,
            "min_candidates": config.min_candidates,
            "max_candidates": config.max_candidates,
        },
        usage_limits=UsageLimits(request_limit=config.framer_request_limit),
    )
    output = _parse_output(result, CandidateSet)
    if output is None:
        raise RuntimeError("Framer returned no valid CandidateSet")
    return output, _cost(result), _tokens(result)


async def _run_framings_validator(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    framer_set: CandidateSet,
) -> tuple[FramingValidation, float, TaskTokenUsage]:
    result = await execute_agent_fn(
        agent_name=config.framings_validator_agent,
        instructions=(
            "Audit this CandidateSet for hidden bias. Approve if it survives "
            "audit; revise with a corrected set if not. See your system "
            "prompt for the procedure."
        ),
        inputs={
            "question": question,
            "candidate_set": framer_set.model_dump(),
        },
        usage_limits=UsageLimits(request_limit=config.framings_validator_request_limit),
    )
    output = _parse_output(result, FramingValidation)
    if output is None:
        raise RuntimeError("Framings validator returned no valid output")
    return output, _cost(result), _tokens(result)


async def _run_side_researcher(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    candidate: CandidateAnswer,
    model: str,
) -> tuple[SidePacket, float, TaskTokenUsage]:
    """Asymmetric research — sees ONLY its own candidate, not the others."""
    result = await execute_agent_fn(
        agent_name=config.side_researcher_agent,
        instructions=(
            f"Steelman research for ONE candidate answer.\n"
            f"Question: {question}\n"
            f"Candidate label: {candidate.label}\n"
            f"Candidate statement: {candidate.statement}\n"
            "Find the strongest evidence that this candidate is correct. "
            "You are an advocate, not balanced. See your system prompt."
        ),
        inputs={
            "question": question,
            "candidate": candidate.model_dump(),
            "_resolved_model": model,  # Honoured in Phase 6 by execute_agent_fn override.
        },
        usage_limits=UsageLimits(request_limit=config.side_researcher_request_limit),
    )
    output = _parse_output(result, SidePacket)
    if output is None:
        raise RuntimeError(f"Side researcher for {candidate.label!r} returned no valid SidePacket")
    return output, _cost(result), _tokens(result)


async def _run_advocate_blind(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    candidate: CandidateAnswer,
    own_packet: SidePacket,
    model: str,
) -> tuple[AdvocateCase, float, TaskTokenUsage]:
    """Blind advocacy — sees ONLY own packet, not others' packets or cases."""
    result = await execute_agent_fn(
        agent_name=config.advocate_agent,
        instructions=(
            f"Write the strongest case for your candidate (blind opening).\n"
            f"Question: {question}\n"
            f"Candidate label: {candidate.label}\n"
            f"Candidate statement: {candidate.statement}\n"
            "You see ONLY your own research packet. See your system prompt."
        ),
        inputs={
            "question": question,
            "candidate": candidate.model_dump(),
            "own_packet": own_packet.model_dump(),
            "_resolved_model": model,
            "_phase": "blind_case",
        },
        usage_limits=UsageLimits(request_limit=config.advocate_request_limit),
    )
    output = _parse_output(result, AdvocateCase)
    if output is None:
        raise RuntimeError(f"Advocate for {candidate.label!r} returned no valid AdvocateCase")
    return output, _cost(result), _tokens(result)


async def _run_advocate_attacks(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    candidate: CandidateAnswer,
    own_case: AdvocateCase,
    all_cases: list[AdvocateCase],
    all_packets: list[SidePacket],
    model: str,
) -> tuple[AttacksByAdvocate, float, TaskTokenUsage]:
    """Bilateral attacks — sees ALL cases + ALL packets, attacks the N-1 others."""
    other_cases = [c.model_dump() for c in all_cases if c.candidate_label != candidate.label]
    result = await execute_agent_fn(
        agent_name=config.advocate_agent,
        instructions=(
            f"Attack the OTHER candidates' load-bearing claims.\n"
            f"Question: {question}\n"
            f"You wrote the case for: {candidate.label}\n"
            f"You now see all other advocates' cases and the union of all "
            "research packets. Produce one Attack per other candidate. "
            "See your system prompt."
        ),
        inputs={
            "question": question,
            "own_label": candidate.label,
            "own_case": own_case.model_dump(),
            "other_cases": other_cases,
            "all_packets": [p.model_dump() for p in all_packets],
            "_resolved_model": model,
            "_phase": "attacks",
        },
        usage_limits=UsageLimits(request_limit=config.advocate_request_limit),
    )
    output = _parse_output(result, AttacksByAdvocate)
    if output is None:
        raise RuntimeError(f"Attacker {candidate.label!r} returned no valid AttacksByAdvocate")
    return output, _cost(result), _tokens(result)


async def _run_judge(
    *,
    config: AdvocateJudgeConfig,
    execute_agent_fn: ExecuteAgentFn,
    question: str,
    candidate_set: CandidateSet,
    packets: list[SidePacket],
    cases: list[AdvocateCase],
    attacks: list[AttacksByAdvocate],
) -> tuple[FinalDeliverable, float, TaskTokenUsage]:
    result = await execute_agent_fn(
        agent_name=config.judge_agent,
        instructions=(
            f"Produce the FinalDeliverable. Question: {question}. "
            "You see everything: the candidate set, every advocate's case "
            "and confidence, every advocate's attacks on others, and the "
            "union of research packets. See your system prompt."
        ),
        inputs={
            "question": question,
            "candidate_set": candidate_set.model_dump(),
            "packets": [p.model_dump() for p in packets],
            "cases": [c.model_dump() for c in cases],
            "attacks": [a.model_dump() for a in attacks],
            "_resolved_model": config.judge_model,
        },
        usage_limits=UsageLimits(request_limit=config.judge_request_limit),
    )
    output = _parse_output(result, FinalDeliverable)
    if output is None:
        raise RuntimeError("Judge returned no valid FinalDeliverable")
    return output, _cost(result), _tokens(result)


# =============================================================================
# Persistence (mirrors deliberation_loop.py pattern)
# =============================================================================


async def _persist_artifacts(
    *,
    mission_id: str,
    question: str,
    candidate_set: CandidateSet,
    packets: list[SidePacket],
    cases: list[AdvocateCase],
    attacks: list[AttacksByAdvocate],
    deliverable: FinalDeliverable,
    side_models: list[str],
) -> None:
    """Three artifacts + a learning entry. Best-effort — logs and continues."""
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
            "architecture": "advocate-judge",
            "side_models": side_models,
            "candidate_set": candidate_set.model_dump(),
            "packets": [p.model_dump() for p in packets],
            "cases": [c.model_dump() for c in cases],
            "attacks": [a.model_dump() for a in attacks],
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
            domain_tags=["deliberation", "cruxes", "advocate-judge"],
            confidence=deliverable.confidence,
        )
    except Exception:
        logger.warning("store-learning failed", exc_info=True)


# =============================================================================
# Utilities (mirror deliberation_loop.py)
# =============================================================================


def _parse_output(result: dict, schema_cls):
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
        agent_name="advocate_judge",
        status=TaskStatus.FAILED,
        output_reference={"error": reason},
        cost_usd=cost,
        token_usage=tokens,
        duration_seconds=round(time.monotonic() - start_time, 2),
    )
