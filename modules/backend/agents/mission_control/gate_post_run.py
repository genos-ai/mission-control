"""
Autonomous Post-Run Gate Reviewer (Plan 51 Phase C).

Implements the 8-branch decision matrix from Plan 51 §4.2 as a
``GateReviewer`` for the ``post_run`` gate checkpoint. Called by
the ``evaluate_post_run`` activity after every executed wave of a
MissionRunWorkflow to decide: wait, advance, refine,
propose-complete, or escalate.

Architecture (Plan 51 §2.3): **rules first, Haiku fallback.**
Seven of eight branches are deterministic Python — no LLM call,
no token cost, no latency. Only branch #8 (plan exhausted +
ambiguous classification) consults Haiku, and Phase D implements
that branch. Phase C stubs it as ``ESCALATE`` (safe default).

Three circuit breakers (§4.6) fire before any rule evaluation:
1. Budget exhausted
3. Stall (N consecutive zero-completion waves)
4. Budget headroom (proactive — estimated next-wave cost > remaining)
Breaker #2, the supervisor iteration cap, was removed by Plan 88 step
88.2.6; the numbers are kept because audit rows record them.

Idempotency (§4.6a): the reviewer queries ``execution_decisions``
for an existing ``post_run_supervisor`` row matching the current
execution_record_id and supervisor iteration (Plan 88 step 88.1.8: one
ExecutionRecord spans every iteration of a run). If present, returns a
cached decision without re-evaluating.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from modules.backend.agents.mission_control.gate_models import (
    GateAction,
    GateContext,
    GateDecision,
)
from modules.backend.core.config import get_app_config
from modules.backend.core.decision_reasoning import (
    decode_decision_reasoning,
    encode_decision_reasoning,
)
from modules.backend.core.logging import get_logger
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_plan import GateMode

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


# Circuit breaker defaults.
DEFAULT_STALL_THRESHOLD = 3
BUDGET_SAFETY_FACTOR = 1.5
DEFAULT_COST_FLOOR_USD = 0.50


class AutonomousPostRunReviewer:
    """Post-run gate reviewer implementing Plan 51 §4.2.

    Constructed with a db session and mission plan context. Called
    via ``review(context)`` per the ``GateReviewer`` protocol.

    Phase C implements all 7 rule-based branches + stubs branch #8
    as ESCALATE. Phase D wires the Haiku agent into branch #8.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        gate_mode: GateMode,
        stall_threshold: int = DEFAULT_STALL_THRESHOLD,
        budget_safety_factor: float = BUDGET_SAFETY_FACTOR,
        cost_floor_usd: float = DEFAULT_COST_FLOOR_USD,
    ) -> None:
        self._session = session
        self._gate_mode = gate_mode
        self._stall_threshold = stall_threshold
        self._budget_safety_factor = budget_safety_factor
        self._cost_floor_usd = cost_floor_usd

    async def review(self, context: GateContext) -> GateDecision:
        """Evaluate the 8-branch decision matrix. First match wins."""
        self._mission_id = context.mission_id
        self._iteration = context.supervisor_iteration_count

        # ── Manual gate mode (Plan 80g) ─────────────────────────────
        # When the mission's gate_mode is GateMode.MANUAL, defer the supervisor
        # decision to an external HTTP client (CLI / TUI / script) via
        # ManualGateReviewer. This stops the autonomy loop from spawning
        # new plans without explicit operator approval.
        if self._gate_mode == GateMode.MANUAL:
            from modules.backend.agents.mission_control.gate_manual import ManualGateReviewer
            from modules.backend.core.config import get_app_config
            from modules.backend.core.database import get_session_factory

            manual = ManualGateReviewer(
                session_factory=get_session_factory(),
                timeout_seconds=get_app_config().gate.manual.timeout_seconds,
                poll_interval_seconds=get_app_config().gate.manual.poll_interval_seconds,
            )
            return await manual.review(context)

        execution_record_id = context.plan_task_summary.get("execution_record_id")

        # ── §4.6a Idempotency check ─────────────────────────────────
        if execution_record_id:
            cached = await self._get_cached_decision(
                execution_record_id, context.supervisor_iteration_count
            )
            if cached is not None:
                logger.info(
                    "Post-run reviewer: returning cached decision",
                    extra={
                        "execution_record_id": execution_record_id,
                        "action": cached.action.value,
                    },
                )
                return cached

        # ── Circuit breakers (§4.6) — fire before rules ─────────────

        # Breaker #1: Budget exhausted
        if context.budget_usd > 0 and context.total_cost_usd >= context.budget_usd:
            return self._decide(
                GateAction.ESCALATE,
                "Budget exhausted — total_spent_usd "
                f"({context.total_cost_usd:.4f}) >= ceiling "
                f"({context.budget_usd:.4f}).",
                execution_record_id=execution_record_id,
                rule=1,
            )

        # Breaker #3: Stall detection
        recent = context.recent_run_outcomes
        if len(recent) >= self._stall_threshold:
            last_n = recent[: self._stall_threshold]
            if all(r.get("completed_task_count", 0) == 0 for r in last_n):
                return self._decide(
                    GateAction.ESCALATE,
                    f"Stall detected: {self._stall_threshold} consecutive "
                    "waves with zero completed tasks.",
                    execution_record_id=execution_record_id,
                    rule=3,
                )

        # ── Decision matrix (§4.2) ──────────────────────────────────

        summary = context.plan_task_summary
        approved_count = summary.get("approved", 0)
        proposed_count = summary.get("proposed", 0)
        has_outcomes = bool(context.recent_run_outcomes)

        # Rule #4: Approved tasks remaining — daemon picks them up
        if approved_count > 0:
            return self._decide(
                GateAction.WAIT,
                f"{approved_count} approved task(s) remaining — " "daemon will dispatch next tick.",
                execution_record_id=execution_record_id,
                rule=4,
            )

        # Rules #5–7: Proposed tasks — action depends on gate_mode
        if proposed_count > 0:
            # Breaker #4: Budget headroom before advancing
            headroom_ok = self._check_budget_headroom(
                context,
                proposed_count,
            )
            if not headroom_ok:
                return self._decide(
                    GateAction.ESCALATE,
                    "Budget headroom insufficient for the next wave. "
                    f"Proposed {proposed_count} tasks but estimated cost "
                    "exceeds remaining budget.",
                    execution_record_id=execution_record_id,
                    rule="4-headroom",
                )

            if self._gate_mode == GateMode.AUTONOMOUS:
                # Rule #5
                return self._decide(
                    GateAction.ADVANCE_APPROVED,
                    f"Auto-advancing {proposed_count} proposed task(s) — "
                    f"gate_mode={self._gate_mode.value}.",
                    execution_record_id=execution_record_id,
                    rule=5,
                )
            elif self._gate_mode == GateMode.AI_ASSISTED:
                # Rule #6
                return self._decide(
                    GateAction.ADVANCE_APPROVED,
                    f"Auto-advancing {proposed_count} proposed task(s) "
                    "with veto window — gate_mode=ai_assisted.",
                    execution_record_id=execution_record_id,
                    rule=6,
                )
            else:
                # Rule #7: interactive
                return self._decide(
                    GateAction.ESCALATE,
                    f"{proposed_count} proposed task(s) ready to advance "
                    "but gate_mode=interactive — escalating for user approval.",
                    execution_record_id=execution_record_id,
                    rule=7,
                )

        # Rule #8: Plan exhausted — no approved, no proposed, outcomes present.
        # This is the ONLY branch that consults Haiku. All other branches
        # are deterministic Python above.
        if has_outcomes:
            haiku_decision = await self._classify_with_haiku(context)
            if haiku_decision is not None:
                return haiku_decision
            # If Haiku fails, fall through to ESCALATE below.

        # Fall-through: unknown situation → ESCALATE (safe default)
        return self._decide(
            GateAction.ESCALATE,
            "No decision matrix branch matched — escalating " "to Director as safe default.",
            execution_record_id=execution_record_id,
            rule="fallthrough",
        )

    # ── Internal helpers ─────────────────────────────────────────────

    def _decide(
        self,
        action: GateAction,
        reason: str,
        *,
        execution_record_id: str | None,
        rule: int | str,
    ) -> GateDecision:
        """Build a GateDecision and write the audit row."""
        # The decision carries the human reason only; the metadata goes to the
        # audit row alone, so it never reaches events, notifications or prompts.
        audit_reasoning = encode_decision_reasoning(
            reason,
            {
                "action": action.value,
                "reviewer": "config:rule_engine",
                "rule": rule,
                "model_metadata": None,
                "iteration": self._iteration,
            },
        )

        decision = GateDecision(
            action=action,
            reason=reason,
            reviewer="config:rule_engine",
            rule=rule,
        )

        # Write audit row (best-effort — don't fail the decision if
        # the audit write errors).
        if execution_record_id:
            try:
                self._write_audit_row(
                    execution_record_id,
                    action,
                    audit_reasoning,
                )
            except Exception:
                # best-effort — don't fail the decision if the audit write errors.
                logger.warning(
                    "Failed to write post-run audit row",
                    extra={
                        "execution_record_id": execution_record_id,
                        "mission_id": self._mission_id,
                    },
                    exc_info=True,
                )

        logger.info(
            "Post-run reviewer decision",
            extra={
                "action": action.value,
                "rule": rule,
                "execution_record_id": execution_record_id,
                "mission_id": self._mission_id,
            },
        )
        return decision

    def _write_audit_row(
        self,
        execution_record_id: str,
        action: GateAction,
        reasoning: str,
    ) -> None:
        """Insert an ExecutionDecision row synchronously.

        Uses the session's add() — the caller owns flush/commit.
        Deliberately synchronous (no await) because SQLAlchemy's
        session.add() is a memory operation; the actual DB write
        happens at the next flush/commit by the caller.
        """
        ExecutionPersistenceService(self._session).add_decision_row(
            execution_record_id,
            "post_run_supervisor",
            reasoning,
        )

    async def _get_cached_decision(
        self,
        execution_record_id: str,
        iteration: int,
    ) -> GateDecision | None:
        """Check for an existing post_run_supervisor decision for this iteration.

        If found, reconstruct the GateDecision from the audit row's
        reasoning field (see ``decision_reasoning`` for the format).
        """
        row = await ExecutionPersistenceService(self._session).get_cached_decision_by_type(
            execution_record_id,
            "post_run_supervisor",
            iteration=iteration,
        )
        if row is None:
            return None

        human_reason, meta = decode_decision_reasoning(row.reasoning or "")
        try:
            action = GateAction(meta.get("action", GateAction.ESCALATE.value))
        except ValueError:
            action = GateAction.ESCALATE

        return GateDecision(
            action=action,
            reason=human_reason,
            reviewer=meta.get("reviewer", "config:rule_engine"),
            model_metadata=meta.get("model_metadata"),
            rule=meta.get("rule"),
        )

    async def _classify_with_haiku(
        self,
        context: GateContext,
    ) -> GateDecision | None:
        """Branch #8: invoke the Haiku supervisor agent for classification.

        Returns a GateDecision on success, or None if the Haiku call
        fails (so the caller can fall through to ESCALATE).

        Confidence < 0.6 is overridden to ESCALATE regardless of the
        agent's stated decision (§4.2 safety rule).
        """
        execution_record_id = context.plan_task_summary.get("execution_record_id")

        try:
            from modules.backend.agents.mission.supervisor.agent import create_event_agent
            from modules.backend.agents.mission.supervisor.deps import MissionSupervisorDeps

            model_name = get_app_config().gate.ai.model
            agent = create_event_agent(model_name)
            deps = MissionSupervisorDeps(
                mission_id=context.mission_id,
                db_session=self._session,
            )

            # Build the prompt with context the Haiku agent needs.
            recent_outcomes_json = json.dumps(
                context.recent_run_outcomes[:3], indent=2, default=str
            )
            plan_task_summary_json = json.dumps(context.plan_task_summary, indent=2, default=str)
            prompt = (
                f"Mission brief: {context.mission_brief or 'not available'}\n\n"
                f"Recent run outcomes:\n{recent_outcomes_json}\n\n"
                f"Plan task summary: {plan_task_summary_json}\n\n"
                f"Budget: spent ${context.total_cost_usd:.4f} "
                f"of ${context.budget_usd:.4f} ceiling.\n\n"
                "Based on the above, classify this situation."
            )

            result = await agent.run(prompt, deps=deps)
            decision = result.output  # SupervisorDecision

            # Usage tracking
            usage = result.usage()
            tokens_used = (usage.input_tokens or 0) + (usage.output_tokens or 0)
            from modules.backend.agents.mission_control.cost import compute_cost_usd

            cost_usd = compute_cost_usd(
                usage.input_tokens or 0,
                usage.output_tokens or 0,
                model_name,
            )

            # Confidence override: < 0.6 → ESCALATE
            if decision.confidence < 0.6:
                logger.info(
                    "Haiku confidence below threshold, overriding to ESCALATE",
                    extra={
                        "stated_decision": decision.decision,
                        "confidence": decision.confidence,
                    },
                )
                return self._decide(
                    GateAction.ESCALATE,
                    f"Haiku classified as {decision.decision} but confidence "
                    f"({decision.confidence:.2f}) is below 0.6 threshold. "
                    f"Reason: {decision.reason}",
                    execution_record_id=execution_record_id,
                    rule="8-low-confidence",
                )

            # Map the decision string to a GateAction.
            action_map = {
                "ADVANCE_REFINE": GateAction.ADVANCE_REFINE,
                "PROPOSE_COMPLETE": GateAction.PROPOSE_COMPLETE,
                "ESCALATE": GateAction.ESCALATE,
            }
            action = action_map.get(
                decision.decision.upper(),
                GateAction.ESCALATE,
            )

            model_metadata = {
                "confidence": decision.confidence,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
            }
            audit_reasoning = encode_decision_reasoning(
                decision.reason,
                {
                    "action": action.value,
                    "reviewer": f"ai:{model_name}",
                    "rule": 8,
                    "model_metadata": model_metadata,
                    "iteration": context.supervisor_iteration_count,
                },
            )

            gate_decision = GateDecision(
                action=action,
                reason=decision.reason,
                reviewer=f"ai:{model_name}",
                model_metadata=model_metadata,
                rule=8,
            )

            # Write audit row
            if execution_record_id:
                try:
                    self._write_audit_row(
                        execution_record_id,
                        action,
                        audit_reasoning,
                    )
                except Exception:
                    # best-effort — don't fail the decision if the audit write errors.
                    logger.warning(
                        "Failed to write Haiku audit row",
                        extra={
                            "execution_record_id": execution_record_id,
                            "mission_id": context.mission_id,
                        },
                        exc_info=True,
                    )

            logger.info(
                "Haiku classification complete",
                extra={
                    "action": action.value,
                    "confidence": decision.confidence,
                    "cost_usd": cost_usd,
                    "execution_record_id": execution_record_id,
                },
            )
            return gate_decision

        except Exception as exc:
            # falling back to the safe default (caller escalates to human
            # review when this returns None) — no event_bus reachable here.
            logger.error(
                "Haiku classification failed, falling through to ESCALATE",
                extra={"error": str(exc), "mission_id": context.mission_id},
                exc_info=True,
            )
            return None

    def _check_budget_headroom(
        self,
        context: GateContext,
        proposed_count: int,
    ) -> bool:
        """Return True if there's enough budget for the next wave.

        Uses observed-average cost estimation per §4.6 breaker #4.
        Returns True (headroom OK) if no ceiling is set.
        """
        if context.budget_usd <= 0:
            return True  # No ceiling — unlimited budget

        remaining = context.budget_usd - context.total_cost_usd
        if remaining <= 0:
            return False  # Already at or over ceiling

        # Estimate next wave cost
        summary = context.plan_task_summary
        completed_so_far = summary.get("total_completed", 0)
        total_spent = context.total_cost_usd

        if completed_so_far > 0 and total_spent > 0:
            avg_cost = total_spent / completed_so_far
            estimated = proposed_count * avg_cost * self._budget_safety_factor
        else:
            estimated = proposed_count * self._cost_floor_usd

        return remaining >= estimated


# ── Utility functions used by the duplicate-work breaker ─────────────


def normalize_task_content(description: str, instructions: str) -> str:
    """Normalize task content for duplicate detection (§4.6 breaker #3).

    Returns a SHA-256 hex digest of the normalized text. Two tasks
    with the same description + instructions (modulo whitespace and
    case) produce the same hash.
    """
    text = f"{description}\n{instructions}"
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
