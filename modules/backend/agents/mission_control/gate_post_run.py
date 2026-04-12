"""
Autonomous Post-Run Gate Reviewer (Plan 51 Phase C).

Implements the 8-branch decision matrix from Plan 51 §4.2 as a
``GateReviewer`` for the ``post_run`` gate checkpoint. Called by
``MissionPlanService.dispatch_approved`` after every completed
wave to decide: wait, advance, refine, propose-complete, or
escalate.

Architecture (Plan 51 §2.3): **rules first, Haiku fallback.**
Seven of eight branches are deterministic Python — no LLM call,
no token cost, no latency. Only branch #8 (plan exhausted +
ambiguous classification) consults Haiku, and Phase D implements
that branch. Phase C stubs it as ``ESCALATE`` (safe default).

Four circuit breakers (§4.6) fire before any rule evaluation:
1. Budget exhausted
2. Max supervisor iterations
3. Stall (N consecutive zero-completion waves)
4. Budget headroom (proactive — estimated next-wave cost > remaining)

Idempotency (§4.6a): the reviewer queries ``execution_decisions``
for an existing ``post_run_supervisor`` row matching the current
execution_record_id. If present, returns a cached decision without
re-evaluating.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.mission_control.gate_models import (
    GateAction,
    GateContext,
    GateDecision,
    GateReviewer,
)
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

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
        gate_mode: str | None = None,
        stall_threshold: int = DEFAULT_STALL_THRESHOLD,
    ) -> None:
        self._session = session
        self._gate_mode = gate_mode or "off"
        self._stall_threshold = stall_threshold

    async def review(self, context: GateContext) -> GateDecision:
        """Evaluate the 8-branch decision matrix. First match wins."""

        execution_record_id = context.plan_task_summary.get("execution_record_id")

        # ── §4.6a Idempotency check ─────────────────────────────────
        if execution_record_id:
            cached = await self._get_cached_decision(execution_record_id)
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

        # Breaker #2: Max supervisor iterations
        max_iter = context.plan_task_summary.get("max_supervisor_iterations", 20)
        if context.supervisor_iteration_count >= max_iter:
            return self._decide(
                GateAction.ESCALATE,
                f"Supervisor iteration limit reached "
                f"({context.supervisor_iteration_count}/{max_iter}).",
                execution_record_id=execution_record_id,
                rule=2,
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
                f"{approved_count} approved task(s) remaining — "
                "daemon will dispatch next tick.",
                execution_record_id=execution_record_id,
                rule=4,
            )

        # Rules #5–7: Proposed tasks — action depends on gate_mode
        if proposed_count > 0:
            # Breaker #4: Budget headroom before advancing
            headroom_ok = self._check_budget_headroom(
                context, proposed_count,
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

            if self._gate_mode in ("off", "autonomous"):
                # Rule #5
                return self._decide(
                    GateAction.ADVANCE_APPROVED,
                    f"Auto-advancing {proposed_count} proposed task(s) — "
                    f"gate_mode={self._gate_mode}.",
                    execution_record_id=execution_record_id,
                    rule=5,
                )
            elif self._gate_mode == "ai_assisted":
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
            "No decision matrix branch matched — escalating "
            "to Director as safe default.",
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
        # Build the structured JSON tail for the reasoning field
        metadata_json = json.dumps({
            "action": action.value,
            "reviewer": "config:rule_engine",
            "rule": rule,
            "model_metadata": None,
        })
        full_reason = f"{reason}\n{metadata_json}"

        decision = GateDecision(
            action=action,
            reason=full_reason,
            reviewer="config:rule_engine",
        )

        # Write audit row (best-effort — don't fail the decision if
        # the audit write errors).
        if execution_record_id:
            try:
                self._write_audit_row(
                    execution_record_id, action, full_reason,
                )
            except Exception:
                logger.warning(
                    "Failed to write post-run audit row",
                    extra={"execution_record_id": execution_record_id},
                    exc_info=True,
                )

        logger.info(
            "Post-run reviewer decision",
            extra={
                "action": action.value,
                "rule": rule,
                "execution_record_id": execution_record_id,
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
        from modules.backend.models.execution_record import (
            DecisionType,
            ExecutionDecision,
        )

        row = ExecutionDecision(
            execution_record_id=execution_record_id,
            decision_type=DecisionType.POST_RUN_SUPERVISOR.value,
            task_id=None,
            reasoning=reasoning,
        )
        self._session.add(row)

    async def _get_cached_decision(
        self, execution_record_id: str,
    ) -> GateDecision | None:
        """Check for an existing post_run_supervisor decision.

        If found, reconstruct the GateDecision from the audit row's
        JSON tail in the reasoning field (see §4.5 encoding).
        """
        from modules.backend.models.execution_record import (
            DecisionType,
            ExecutionDecision,
        )

        stmt = select(ExecutionDecision).where(
            and_(
                ExecutionDecision.execution_record_id == execution_record_id,
                ExecutionDecision.decision_type == DecisionType.POST_RUN_SUPERVISOR.value,
            )
        ).limit(1)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        # Parse the JSON tail from the reasoning field.
        reasoning = row.reasoning or ""
        meta: dict[str, Any] = {}
        try:
            last_line = reasoning.strip().rsplit("\n", 1)[-1]
            meta = json.loads(last_line)
            action_str = meta.get("action", "escalate")
            action = GateAction(action_str)
        except (json.JSONDecodeError, ValueError, KeyError):
            action = GateAction.ESCALATE

        return GateDecision(
            action=action,
            reason=reasoning,
            reviewer=meta.get("reviewer", "config:rule_engine"),
            model_metadata=meta.get("model_metadata"),
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
            from modules.backend.agents.mission.supervisor.agent import (
                create_event_agent,
            )
            from modules.backend.agents.mission.supervisor.deps import (
                MissionSupervisorDeps,
            )

            agent = create_event_agent("anthropic:claude-haiku-4-5-20251001")
            deps = MissionSupervisorDeps(
                mission_id=context.mission_id,
                db_session=self._session,
            )

            # Build the prompt with context the Haiku agent needs.
            prompt = (
                f"Mission brief: {context.mission_brief or 'not available'}\n\n"
                f"Recent run outcomes:\n{json.dumps(context.recent_run_outcomes[:3], indent=2, default=str)}\n\n"
                f"Plan task summary: {json.dumps(context.plan_task_summary, indent=2, default=str)}\n\n"
                f"Budget: spent ${context.total_cost_usd:.4f} of ${context.budget_usd:.4f} ceiling.\n\n"
                "Based on the above, classify this situation."
            )

            result = await agent.run(prompt, deps=deps)
            decision = result.output  # SupervisorDecision

            # Usage tracking
            usage = result.usage()
            tokens_used = (usage.input_tokens or 0) + (usage.output_tokens or 0)
            from modules.backend.core.cost import compute_cost_usd
            cost_usd = compute_cost_usd(
                usage.input_tokens or 0,
                usage.output_tokens or 0,
                "anthropic:claude-haiku-4-5-20251001",
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
                decision.decision.upper(), GateAction.ESCALATE,
            )

            metadata_json = json.dumps({
                "action": action.value,
                "reviewer": "ai:claude-haiku-4-5-20251001",
                "rule": 8,
                "model_metadata": {
                    "confidence": decision.confidence,
                    "tokens_used": tokens_used,
                    "cost_usd": cost_usd,
                },
            })
            full_reason = f"{decision.reason}\n{metadata_json}"

            gate_decision = GateDecision(
                action=action,
                reason=full_reason,
                reviewer="ai:claude-haiku-4-5-20251001",
                model_metadata={
                    "confidence": decision.confidence,
                    "tokens_used": tokens_used,
                    "cost_usd": cost_usd,
                },
            )

            # Write audit row
            if execution_record_id:
                try:
                    self._write_audit_row(
                        execution_record_id, action, full_reason,
                    )
                except Exception:
                    logger.warning(
                        "Failed to write Haiku audit row",
                        extra={"execution_record_id": execution_record_id},
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
            logger.error(
                "Haiku classification failed, falling through to ESCALATE",
                extra={"error": str(exc)},
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
            estimated = proposed_count * avg_cost * BUDGET_SAFETY_FACTOR
        else:
            estimated = proposed_count * DEFAULT_COST_FLOOR_USD

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
