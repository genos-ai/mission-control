"""Gate data models — enums, dataclasses, and protocol definition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class GateAction(str, Enum):
    """Reviewer actions at a gate point."""

    CONTINUE = "continue"   # Proceed to next step
    SKIP = "skip"           # Skip this task/layer, mark SKIPPED
    RETRY = "retry"         # Re-run the task (with optional modified inputs)
    ABORT = "abort"         # Halt the entire mission
    MODIFY = "modify"       # Proceed with modified inputs/instructions


@dataclass
class GateContext:
    """Everything the reviewer needs to make a decision.

    All fields are JSON-serializable so both CLI and AI reviewers
    can consume the same data.
    """

    gate_type: str               # pre_dispatch, pre_layer, post_task,
                                 # verification_failed, post_layer
    mission_id: str
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


@dataclass
class GateDecision:
    """Reviewer's decision at a gate point."""

    action: GateAction
    reason: str | None = None
    modified_inputs: dict | None = None        # For MODIFY action
    modified_instructions: str | None = None   # For RETRY with feedback
    reviewer: str = "human"                    # human, ai:<model>, noop, config:disabled


class GateReviewer(Protocol):
    """Abstract reviewer — human, AI, or composite.

    Implementations:
    - NoOpGate: always continues (off mode)
    - CliGateReviewer: interactive Rich prompts (interactive mode)
    - LlmGateReviewer: thinking LLM reviews (autonomous mode)
    - ConfigurableGate: per-gate-point mode routing (ai_assisted, mixed)
    """

    async def review(self, context: GateContext) -> GateDecision: ...


class NoOpGate:
    """Pass-through gate that always continues. Zero overhead."""

    async def review(self, context: GateContext) -> GateDecision:
        return GateDecision(action=GateAction.CONTINUE, reviewer="noop")
