"""Gate data models — enums, dataclasses, and protocol definition.

Shared types for the gate review system (pre_dispatch, post_task, post_run).
Consumed by services, agents, and temporal activities.

Extracted from agents/mission_control/gate_models.py (import cycle fix).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class GateAction(str, Enum):
    """Reviewer actions at a gate point."""

    # Standard actions (pre_dispatch, pre_layer, post_task, post_layer)
    CONTINUE = "continue"   # Proceed to next step
    SKIP = "skip"           # Skip this task/layer, mark SKIPPED
    RETRY = "retry"         # Re-run the task (with optional modified inputs)
    ABORT = "abort"         # Halt the entire mission
    MODIFY = "modify"       # Proceed with modified inputs/instructions

    # Post-run autonomy loop actions (Plan 51 Phase C — valid only at post_run)
    WAIT = "wait"                       # Daemon has approved tasks to dispatch; no action
    ADVANCE_APPROVED = "advance_approved"   # Proposed → approved; daemon picks them up
    ADVANCE_REFINE = "advance_refine"      # Wake Planning Agent to generate next wave
    PROPOSE_COMPLETE = "propose_complete"   # Wake Director to ask user if mission is done
    ESCALATE = "escalate"                  # Wake Director for user attention


@dataclass
class GateContext:
    """Everything the reviewer needs to make a decision.

    All fields are JSON-serializable so both CLI and AI reviewers
    can consume the same data.
    """

    gate_type: str               # pre_dispatch, pre_layer, post_task,
                                 # verification_failed, post_layer, post_run
    mission_id: str
    # Session is the transport primitive (P15) — gates fire within an
    # execution session. Optional to keep older callers compiling; should
    # be populated by every dispatcher.
    session_id: str | None = None
    layer_index: int = 0
    total_layers: int = 0

    # Pre-layer: tasks about to execute
    pending_tasks: list[dict] = field(default_factory=list)

    # Post-task: completed task details
    task_id: str | None = None
    task_result: dict | None = None     # TaskResult as dict
    task_output: dict | None = None     # Raw agent output
    verification: dict | None = None    # VerificationOutcome as dict

    # Aggregates
    completed_tasks: list[dict] = field(default_factory=list)
    total_cost_usd: float = 0.0
    budget_usd: float = 0.0

    # For retry/modify
    current_instructions: str | None = None
    current_inputs: dict | None = None

    # AI reviewer recommendation (populated by ConfigurableGate in ai_assisted mode)
    ai_recommendation: Any = None

    # Post-run fields (Plan 51 Phase C — populated only for gate_type="post_run")
    recent_run_outcomes: list[dict] = field(default_factory=list)
    plan_task_summary: dict = field(default_factory=dict)
    mission_brief: str | None = None
    supervisor_iteration_count: int = 0


@dataclass
class GateDecision:
    """Reviewer's decision at a gate point."""

    action: GateAction
    reason: str | None = None
    modified_inputs: dict | None = None        # For MODIFY action
    modified_instructions: str | None = None   # For RETRY with feedback
    reviewer: str = "human"                    # human, ai:<model>, noop, config:disabled, config:rule_engine
    model_metadata: dict | None = None         # Plan 51: {confidence, tokens_used, cost_usd} when LLM decides


class GateReviewer(Protocol):
    """Abstract reviewer — human, AI, or composite."""

    async def review(self, context: GateContext) -> GateDecision: ...


class NoOpGate:
    """Pass-through gate that always continues. Zero overhead."""

    async def review(self, context: GateContext) -> GateDecision:
        return GateDecision(action=GateAction.CONTINUE, reviewer="noop")
