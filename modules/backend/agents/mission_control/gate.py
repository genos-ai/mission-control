"""
Step-Through Gate — human/AI-in-the-loop review mechanism.

Pauses execution at key decision points in the dispatch loop, presents
context, and waits for a reviewer (human or AI) to approve, reject,
modify, skip, or retry before proceeding.

Modes (configured in config/settings/gate.yaml):
    off          — NoOpGate (default). Zero overhead.
    interactive  — CliGateReviewer via Rich prompts.
    ai_assisted  — LLM recommends, human decides.
    autonomous   — LLM decides, no human.

CLI override: --gate <mode>  (--step is an alias for --gate interactive)

Data models: gate_models.py
Prompt construction: gate_prompt.py
"""

from __future__ import annotations

from typing import Any

# Re-export models for callers that import from gate directly
from modules.backend.agents.mission_control.gate_models import (  # noqa: F401
    GateAction,
    GateContext,
    GateDecision,
    GateReviewer,
    NoOpGate,
)
from modules.backend.agents.mission_control.gate_prompt import (
    _GATE_SYSTEM_PROMPT,
    _build_gate_prompt,
    _parse_action,
)
from modules.backend.core.logging import get_logger
from modules.backend.services.mission_plan import GateMode

logger = get_logger(__name__)


class LlmGateReviewer:
    """AI gate reviewer — uses an LLM to analyze gate context and decide.

    Serializes GateContext into a structured prompt, calls the LLM with
    a JSON-output instruction, and parses the response into a GateDecision.
    """

    def __init__(
        self,
        model: str,
        max_tokens: int,
    ):
        self.model_name = model
        self.max_tokens = max_tokens
        self._agent = None  # Lazy init to avoid import cost when unused

    def _get_agent(self):
        """Lazily build the PydanticAI agent on first use."""
        if self._agent is not None:
            return self._agent

        from pydantic import BaseModel, Field
        from pydantic_ai import Agent

        from modules.backend.agents.mission_control.helpers import _build_model

        class GateReviewOutput(BaseModel):
            """Structured output from the AI gate reviewer."""

            action: str = Field(
                description="One of: continue, skip, retry, abort, modify",
            )
            reason: str = Field(
                default="",
                description="Brief explanation for the decision",
            )
            modified_instructions: str | None = Field(
                default=None,
                description="Feedback for retry (only when action=retry)",
            )

        model = _build_model(self.model_name)

        self._agent = Agent(
            model,
            instructions=_GATE_SYSTEM_PROMPT,
            output_type=GateReviewOutput,
        )
        return self._agent

    async def review(self, context: GateContext) -> GateDecision:
        """Analyze gate context and return a structured decision."""
        agent = self._get_agent()
        user_prompt = _build_gate_prompt(context)

        try:
            result = await agent.run(
                user_prompt,
                model_settings={"max_tokens": self.max_tokens},
            )
            output = result.output
            action = _parse_action(output.action)
            return GateDecision(
                action=action,
                reason=output.reason or None,
                modified_instructions=output.modified_instructions,
                reviewer=f"ai:{self.model_name}",
            )
        except Exception:
            logger.error(
                "LLM gate review failed, aborting for safety",
                exc_info=True,
            )
            return GateDecision(
                action=GateAction.ABORT,
                reason="LLM review failed — aborting for safety",
                reviewer=f"ai:{self.model_name}:fallback",
            )


class ConfigurableGate:
    """Gate that routes to the appropriate reviewer per gate point.

    Reads GateSchema config and routes each gate_type to the correct
    reviewer based on the effective mode (per-point override or top-level).
    """

    def __init__(
        self,
        config: Any,  # GateSchema from config_schema.py
        console: Any = None,  # Rich Console for CLI modes
        verbose: bool = False,
        session_factory: Any = None,  # callable yielding AsyncSession; required for `manual` mode
        event_bus: Any = None,  # SessionEventBus; optional, used by `manual` for lifecycle events
    ):
        from modules.backend.core.config_schema import GateSchema

        if not isinstance(config, GateSchema):
            raise TypeError(f"Expected GateSchema, got {type(config).__name__}")

        self._config = config
        self._console = console
        self._verbose = verbose
        self._session_factory = session_factory
        self._event_bus = event_bus

        self._llm: LlmGateReviewer | None = None
        self._cli: Any = None  # CliGateReviewer — lazy to avoid Rich import
        self._manual: Any = None  # ManualGateReviewer — lazy

    def _get_llm(self) -> LlmGateReviewer:
        if self._llm is None:
            ai = self._config.ai
            self._llm = LlmGateReviewer(
                model=ai.model,
                max_tokens=ai.max_tokens,
            )
        return self._llm

    def _get_cli(self):
        if self._cli is None:
            from modules.clients.cli.gate import CliGateReviewer

            self._cli = CliGateReviewer(
                console=self._console,
                verbose=self._verbose,
            )
        return self._cli

    def _get_manual(self):
        if self._manual is None:
            if self._session_factory is None:
                raise RuntimeError(
                    "Gate mode 'manual' requires a session_factory at "
                    "ConfigurableGate construction time. Update create_gate() "
                    "callers to pass the AsyncSession factory.",
                )
            from modules.backend.agents.mission_control.gate_manual import ManualGateReviewer
            from modules.backend.core.config import get_app_config

            self._manual = ManualGateReviewer(
                session_factory=self._session_factory,
                timeout_seconds=get_app_config().gate.manual.timeout_seconds,
                poll_interval_seconds=get_app_config().gate.manual.poll_interval_seconds,
                event_bus=self._event_bus,
            )
        return self._manual

    def _effective_mode(self, gate_type: str) -> str:
        point_config = getattr(self._config.points, gate_type, None)
        if point_config and point_config.mode is not None:
            return point_config.mode
        return self._config.mode

    def _is_enabled(self, gate_type: str) -> bool:
        point_config = getattr(self._config.points, gate_type, None)
        if point_config is None:
            return True
        return point_config.enabled

    def _should_auto_continue(self, context: GateContext) -> bool:
        """Check auto-continue rules for autonomous mode."""
        rules = self._config.auto_rules

        if context.budget_usd > 0:
            cost_pct = (context.total_cost_usd / context.budget_usd) * 100
            if cost_pct >= rules.cost_threshold_pct:
                return False

        if context.gate_type == "pre_layer":
            if len(context.pending_tasks) <= rules.max_tasks_per_layer:
                return True

        if context.gate_type == "post_task" and rules.skip_post_task_on_pass:
            if context.verification:
                tier1 = context.verification.get("tier_1", {})
                tier2 = context.verification.get("tier_2", {})
                if tier1.get("status") != "fail" and tier2.get("status") != "fail":
                    return True

        if context.gate_type == "verification_failed":
            return False

        if context.gate_type == "pre_dispatch":
            return False

        if context.gate_type == "post_layer":
            return True

        return False

    async def review(self, context: GateContext) -> GateDecision:
        """Route to the appropriate reviewer based on config.

        Note: ``post_run`` gate type (Plan 51 Phase C) is NOT routed
        through ConfigurableGate — it's called directly via
        ``AutonomousPostRunReviewer`` from ``MissionPlanService.
        dispatch_approved`` which owns the db session and mission
        context the reviewer needs. ConfigurableGate only handles
        the standard gate types (pre_dispatch, pre_layer, post_task,
        verification_failed, post_layer).
        """
        gate_type = context.gate_type

        if not self._is_enabled(gate_type):
            return GateDecision(
                action=GateAction.CONTINUE,
                reviewer="config:disabled",
            )

        effective_mode = self._effective_mode(gate_type)

        if effective_mode == GateMode.INTERACTIVE:
            return await self._get_cli().review(context)

        if effective_mode == GateMode.MANUAL:
            return await self._get_manual().review(context)

        if effective_mode == GateMode.AI_ASSISTED:
            recommendation = await self._get_llm().review(context)
            context.ai_recommendation = recommendation
            return await self._get_cli().review(context)

        if effective_mode == GateMode.AUTONOMOUS:
            if self._should_auto_continue(context):
                return GateDecision(
                    action=GateAction.CONTINUE,
                    reason="auto-rule: conditions met",
                    reviewer="config:auto",
                )
            return await self._get_llm().review(context)

        logger.error("Unknown gate mode %r: aborting (fail closed)", effective_mode)
        return GateDecision(
            action=GateAction.ABORT,
            reason=f"unknown gate mode {effective_mode!r}",
            reviewer=f"config:invalid_mode:{effective_mode}",
        )


def create_gate(
    mode_override: GateMode | None = None,
    console: Any = None,
    verbose: bool = False,
    session_factory: Any = None,
    event_bus: Any = None,
) -> GateReviewer:
    """Create the appropriate gate reviewer from config + CLI override.

    ``session_factory`` is only required when the effective gate mode is
    ``manual`` (which persists pause rows). If omitted, the global async
    session factory is used; pass an explicit one for tests.

    ``event_bus`` is optional. When provided, ``manual`` mode emits
    GateRequestOpenedEvent so watchers can react in real time.
    """
    from modules.backend.core.config import get_app_config
    from modules.backend.core.database import get_session_factory

    config = get_app_config().gate

    if mode_override is not None:
        config = config.model_copy(update={"mode": GateMode(mode_override).value})

    return ConfigurableGate(
        config=config,
        console=console,
        verbose=verbose,
        session_factory=session_factory or get_session_factory(),
        event_bus=event_bus,
    )
