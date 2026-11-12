"""
Session Event Hierarchy.

Real-time agent lifecycle events published via Redis Pub/Sub within a session.
These are ephemeral — not persisted by the event bus. PostgreSQL persistence
happens via the session/memory layer (Phase 2).

All session events extend SessionEvent (not EventEnvelope — different base,
different transport, different purpose).

Event type registry maps event_type strings to Pydantic model classes
for type-safe deserialization.
"""

import uuid

from pydantic import Field

from modules.backend.core.logging import get_logger
from modules.backend.events.base import SessionEvent
from modules.backend.events.mission_run_types import (
    ContextCompactedEvent,
    MissionRunCreatedEvent,
    MissionRunOccurrenceRecordedEvent,
    MissionRunStatusChangedEvent,
    MissionScheduleChangedEvent,
    MissionScheduleSyncFailedEvent,
    TaskFailedEvent,
)

logger = get_logger(__name__)


# =============================================================================
# User Events
# =============================================================================


class UserMessageEvent(SessionEvent):
    """User sent a message to the session."""

    event_type: str = "user.message.sent"
    content: str
    channel: str
    attachments: list[str] = Field(default_factory=list)


class UserApprovalEvent(SessionEvent):
    """User responded to an approval request."""

    event_type: str = "user.approval.granted"
    decision: str
    approval_request_id: str
    reason: str | None = None
    modified_params: dict = Field(default_factory=dict)


# =============================================================================
# Agent Events
# =============================================================================


class AgentThinkingEvent(SessionEvent):
    """Agent started processing (thinking indicator)."""

    event_type: str = "agent.thinking.started"
    agent_id: str


class AgentToolCallEvent(SessionEvent):
    """Agent invoked a tool."""

    event_type: str = "agent.tool.called"
    agent_id: str
    tool_name: str
    tool_args: dict = Field(default_factory=dict)
    tool_call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class AgentToolResultEvent(SessionEvent):
    """Tool returned a result to the agent."""

    event_type: str = "agent.tool.returned"
    agent_id: str
    tool_name: str
    tool_call_id: str
    result: str | None = None
    status: str = "success"
    error_detail: str | None = None


class AgentResponseChunkEvent(SessionEvent):
    """Streaming response chunk from agent."""

    event_type: str = "agent.response.chunk"
    agent_id: str
    content: str
    is_final: bool = False


class AgentResponseCompleteEvent(SessionEvent):
    """Agent completed its full response."""

    event_type: str = "agent.response.complete"
    agent_id: str
    full_content: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


# =============================================================================
# Approval Events
# =============================================================================


class ApprovalRequestedEvent(SessionEvent):
    """Agent requests human-in-the-loop approval."""

    event_type: str = "agent.approval.requested"
    approval_request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    action: str
    context: dict = Field(default_factory=dict)
    allowed_decisions: list[str] = Field(default_factory=lambda: ["approve", "deny"])
    responder_options: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300


class ApprovalResponseEvent(SessionEvent):
    """Approval decision received (from human or auto-policy)."""

    event_type: str = "approval.response.received"
    approval_request_id: str
    decision: str
    responder_type: str = "human"
    responder_id: str | None = None
    reason: str | None = None
    modified_params: dict = Field(default_factory=dict)


# =============================================================================
# Plan Events
# =============================================================================


class PlanningPhaseEvent(SessionEvent):
    """Lightweight status update during the planning phase."""

    event_type: str = "plan.phase"
    step: str  # e.g. "roster", "context", "thinking"
    message: str


class PlanCreatedEvent(SessionEvent):
    """Multi-step plan was created."""

    event_type: str = "plan.created"
    plan_id: str
    goal: str
    step_count: int


class PlanStepStartedEvent(SessionEvent):
    """A plan step started execution."""

    event_type: str = "plan.step.started"
    plan_id: str
    step_id: str
    step_name: str
    assigned_agent: str


class PlanStepCompletedEvent(SessionEvent):
    """A plan step completed."""

    event_type: str = "plan.step.completed"
    plan_id: str
    step_id: str
    result_summary: str
    status: str


class PlanRevisedEvent(SessionEvent):
    """Plan was revised mid-execution."""

    event_type: str = "plan.revised"
    plan_id: str
    revision_reason: str
    steps_added: int = 0
    steps_removed: int = 0
    steps_modified: int = 0


# =============================================================================
# Cost Events
# =============================================================================


class CostUpdateEvent(SessionEvent):
    """Session cost was updated after an LLM call."""

    event_type: str = "session.cost.updated"
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cumulative_cost_usd: float
    budget_remaining_usd: float | None = None
    model: str
    source_event_type: str = ""


# =============================================================================
# Workflow Events
# =============================================================================


class WorkflowRunStartedEvent(SessionEvent):
    event_type: str = "workflow.run.started"
    workflow_run_id: str
    workflow_name: str
    workflow_version: int
    step_count: int
    trigger_type: str
    triggered_by: str


class WorkflowExecutionStartedEvent(SessionEvent):
    event_type: str = "workflow.execution.started"
    workflow_run_id: str
    mission_id: str
    step_id: str
    roster_ref: str
    complexity_tier: str


class WorkflowExecutionCompletedEvent(SessionEvent):
    event_type: str = "workflow.execution.completed"
    workflow_run_id: str
    mission_id: str
    step_id: str
    success: bool
    cost_usd: float = 0.0


class WorkflowRunCompletedEvent(SessionEvent):
    event_type: str = "workflow.run.completed"
    workflow_run_id: str
    workflow_name: str
    total_cost_usd: float
    mission_count: int
    elapsed_seconds: float | None = None
    result_summary: str | None = None


class WorkflowRunFailedEvent(SessionEvent):
    event_type: str = "workflow.run.failed"
    workflow_run_id: str
    workflow_name: str
    error: str
    failed_step: str | None = None
    total_cost_usd: float = 0.0


class WorkflowConditionEvaluatedEvent(SessionEvent):
    event_type: str = "workflow.condition.evaluated"
    workflow_run_id: str
    step_id: str
    expression: str
    result: bool
    branch: str  # "Yes" or "No"


class WorkflowNotificationSentEvent(SessionEvent):
    event_type: str = "workflow.notification.sent"
    workflow_run_id: str
    step_id: str
    channel: str
    success: bool


class WorkflowToolCallCompletedEvent(SessionEvent):
    event_type: str = "workflow.tool_call.completed"
    workflow_run_id: str
    step_id: str
    tool_name: str
    success: bool


class WorkflowLlmCallCompletedEvent(SessionEvent):
    event_type: str = "workflow.llm_call.completed"
    workflow_run_id: str
    step_id: str
    model: str
    success: bool


class WorkflowBranchPassedEvent(SessionEvent):
    event_type: str = "workflow.branch.passed"
    workflow_run_id: str
    step_id: str
    fork_count: int


class WorkflowMergeCompletedEvent(SessionEvent):
    event_type: str = "workflow.merge.completed"
    workflow_run_id: str
    step_id: str
    strategy: str
    inputs_merged: int


class WorkflowSubWorkflowCompletedEvent(SessionEvent):
    event_type: str = "workflow.sub_workflow.completed"
    workflow_run_id: str
    step_id: str
    child_run_id: str
    success: bool
    child_cost_usd: float


class WorkflowDecisionResolvedEvent(SessionEvent):
    """Emitted when a decision node resolves its routing choice."""

    event_type: str = "workflow.decision.resolved"
    workflow_run_id: str
    step_id: str
    resolver: str
    chosen_option: str
    options: list[str]


class WorkflowStepSkippedEvent(SessionEvent):
    event_type: str = "workflow.step.skipped"
    workflow_run_id: str
    step_id: str
    reason: str


class WorkflowHumanInputRequestedEvent(SessionEvent):
    event_type: str = "workflow.human_input.requested"
    workflow_run_id: str
    step_id: str
    request_id: str
    prompt_message: str
    channel: str
    choices: list[str] = Field(default_factory=list)
    timeout_at: str | None = None


class WorkflowHumanInputRespondedEvent(SessionEvent):
    event_type: str = "workflow.human_input.responded"
    workflow_run_id: str
    step_id: str
    request_id: str
    response: str
    responder_id: str = ""
    timed_out: bool = False


# =============================================================================
# Workflow Design Events
# =============================================================================


class WorkflowGraphEvent(SessionEvent):
    """Workflow Architect emitted an updated graph for frontend rendering."""

    event_type: str = "workflow.graph.updated"
    graph_data: dict = Field(default_factory=dict)
    workflow_name: str = ""
    step_count: int = 0


# =============================================================================
# Convergence Loop Events
# =============================================================================


class ConvergenceIterationEvent(SessionEvent):
    """A single evaluation/remediation cycle completed in a convergence loop."""

    event_type: str = "convergence.iteration"
    loop_task_id: str
    cycle_number: int
    findings_count: int
    fixes_applied: int
    convergence_metric: float | None = None
    converged: bool = False


class ConvergenceCompletedEvent(SessionEvent):
    """A convergence loop finished (converged or hit max iterations)."""

    event_type: str = "convergence.completed"
    loop_task_id: str
    total_cycles: int
    final_metric: float | None = None
    outcome: str  # "converged", "max_iterations", "aborted", "verification_failed"


class FinalVerificationEvent(SessionEvent):
    """Clean-slate verification after convergence loop."""

    event_type: str = "convergence.verification"
    loop_task_id: str
    passed: bool
    test_summary: str
    environment_mode: str  # "local", "container"


# =============================================================================
# Mission-level Narrative & Artifact Events (platform primitives)
# =============================================================================


class MissionNarrativeEvent(SessionEvent):
    """Human-readable narrative update from a mission agent.

    Emitted at key execution moments (step start, tool activity, step complete).
    These are the primary building blocks for a live mission feed.
    """

    event_type: str = "mission.narrative"
    mission_id: str
    agent_id: str = ""
    narrative: str  # Short markdown string — one sentence, no headings
    phase: str = ""  # "planning" | "executing" | "analyzing" | "complete" | "error"
    level: str = "info"  # "info" | "success" | "warning"


class MissionArtifactFoundEvent(SessionEvent):
    """An agent produced or discovered a significant artifact.

    Emitted when an agent completes and returns a meaningful result
    (report summary, findings list, generated code, etc.).
    """

    event_type: str = "mission.artifact.found"
    mission_id: str
    agent_id: str = ""
    artifact_type: str  # "report" | "finding" | "code" | "data" | "file"
    title: str
    content: str
    content_type: str = "markdown"  # "text" | "markdown" | "json" | "code"
    language: str = ""  # For code artifacts (python, typescript, etc.)


# =============================================================================
# Mission Plan Events (Plan 42 §3.5)
# =============================================================================
#
# These events sit at the "persistent plan" semantic level, distinct from
# the existing `plan.*` events (which are run-scoped, emitted by the
# dispatch loop). Consumers of `mission_plan.*` should refetch the plan
# via GET /missions/{id}/plan on receipt; the events are invalidation
# signals, not deltas.


class MissionPlanRefinedEvent(SessionEvent):
    """The mission plan was refined via the Planning Agent.

    Emitted after `MissionPlanOrchestrator.refine` reconciles tasks
    and bumps `version`. Frontend subscribes and
    invalidates its cached plan so the Plan tab reflects the change
    immediately.
    """

    event_type: str = "mission_plan.refined"
    mission_id: str
    plan_id: str
    version: int
    task_count: int
    cancelled_count: int = 0  # Task states cancelled by reconciliation
    new_count: int = 0  # New task states created


class MissionPlanTaskStatusChangedEvent(SessionEvent):
    """A plan task transitioned to a new status.

    Emitted on approve / reject / retry / queued / run completion. One
    event per state transition (the backend may emit multiple for a
    single action — e.g. approving a task with 2 transitive deps yields
    3 events, one per affected task_id).
    """

    event_type: str = "mission_plan.task.status_changed"
    mission_id: str
    plan_id: str
    task_id: str
    from_status: str
    to_status: str
    actor: str = ""  # "user:<id>" | "agent:<name>" | "system"


class MissionPlanGateModeChangedEvent(SessionEvent):
    """The plan's autonomy mode was changed."""

    event_type: str = "mission_plan.gate_mode_changed"
    mission_id: str
    plan_id: str
    from_mode: str | None = None
    to_mode: str | None = None


# =============================================================================
# System / Mission-level Events
# =============================================================================


class SystemEvent(SessionEvent):
    """Mission-level system event for the console."""

    event_type: str = "system.info"
    level: str = "info"  # info, warning, error
    message: str = ""
    mission_id: str = ""


class SystemExecutionCreatedEvent(SessionEvent):
    """An execution was created for a mission."""

    event_type: str = "system.execution.created"
    execution_id: str = ""
    mission_id: str = ""
    objective: str = ""
    triggered_by: str = ""


class SystemExecutionCompletedEvent(SessionEvent):
    """An execution completed (success or failure)."""

    event_type: str = "system.execution.completed"
    execution_id: str = ""
    mission_id: str = ""
    status: str = ""
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    task_count: int = 0


class SystemBudgetWarningEvent(SessionEvent):
    """Budget threshold exceeded."""

    event_type: str = "system.budget.warning"
    mission_id: str = ""
    current_cost_usd: float = 0.0
    budget_usd: float = 0.0
    message: str = ""


class SystemSessionCreatedEvent(SessionEvent):
    """A new session was created in a mission."""

    event_type: str = "system.session.created"
    target_session_id: str = ""
    mission_id: str = ""
    agent_id: str = ""
    goal: str = ""


class SupervisorDecisionEmittedEvent(SessionEvent):
    """The post-run supervisor just made a decision (Plan 51 Phase E).

    Emitted by ``AutonomousPostRunReviewer`` in ``gate_post_run.py``
    after writing the audit row. The Director's session followup
    subscribes to this event type so it can wake and post a proactive
    chat update to the user.
    """

    event_type: str = "mission_plan.supervisor_decision"
    mission_id: str = ""
    plan_id: str = ""
    execution_record_id: str = ""
    action: str = ""
    reason: str = ""
    reviewer: str = ""


class GateRequestOpenedEvent(SessionEvent):
    """A manual gate paused; awaiting an external decision (Plan 80g).

    Emitted by ``ManualGateReviewer`` after persisting the GateRequest
    row. Watchers (TUI, web UI, scripts) can subscribe to surface a
    "pending approval" notification without polling.
    """

    event_type: str = "gate.request.opened"
    request_id: str = ""
    mission_id: str = ""
    gate_type: str = ""
    timeout_seconds: int = 0


class GateRequestDecidedEvent(SessionEvent):
    """A manual gate received a decision (Plan 80g).

    Emitted from the /decide endpoint after the decision_json is
    persisted and the dispatcher's asyncio.Event is fired.
    """

    event_type: str = "gate.request.decided"
    request_id: str = ""
    mission_id: str = ""
    gate_type: str = ""
    action: str = ""
    reason: str | None = None
    reviewer: str = ""


# =============================================================================
# Session Followup Events (Plan 51 Phase A)
# =============================================================================


class SessionFollowupFiredEvent(SessionEvent):
    """A session followup was triggered by an event match (Plan 51 Phase A).

    Emitted by ``SessionFollowupService.fire_matching`` after each
    followup fires (success or failure). Used for audit logging and
    frontend notifications.
    """

    event_type: str = "session.followup.fired"
    followup_id: str = ""
    mission_id: str = ""
    trigger_event_type: str = ""
    created_by_agent: str = ""
    success: bool = True
    failure_reason: str = ""


# =============================================================================
# Knowledge Events (Plan 57)
# =============================================================================


class MissionIntentRevisedEvent(SessionEvent):
    """A mission's intent was revised (user or Director)."""

    event_type: str = "knowledge.intent.revised"
    intent_id: str = ""
    old_intent_summary: str = ""
    new_intent_summary: str = ""
    reason: str = ""
    intent_source: str = ""  # user_chat | user_cli | director_inferred | system


class MissionLearningExtractedEvent(SessionEvent):
    """A new learning was extracted from execution history."""

    event_type: str = "knowledge.learning.extracted"
    learning_id: str = ""
    kind: str = ""
    title: str = ""
    domain_tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class PlatformLearningPromotedEvent(SessionEvent):
    """A mission learning was promoted to platform scope."""

    event_type: str = "knowledge.learning.promoted"
    learning_id: str = ""
    promoted_by: str = ""


class LearningContradictionFlaggedEvent(SessionEvent):
    """Two learnings were flagged as contradictory by the Officer."""

    event_type: str = "knowledge.contradiction.flagged"
    learning_ids: list[str] = Field(default_factory=list)
    reason: str = ""


# =============================================================================
# Research Events (Plan 40 §7.2)
# =============================================================================


class ResearchStartedEvent(SessionEvent):
    """A deep research loop has started."""

    event_type: str = "research.started"
    research_id: str
    query: str
    depth: str = "comprehensive"
    max_iterations: int = 5


class ResearchDecomposedEvent(SessionEvent):
    """The strategist decomposed a query into sub-questions."""

    event_type: str = "research.decomposed"
    research_id: str
    sub_question_count: int = 0
    sub_questions: list[dict] = Field(default_factory=list)


class ResearchSubQuestionUpdatedEvent(SessionEvent):
    """A sub-question's status changed (pending → searching → covered → gap)."""

    event_type: str = "research.subquestion.updated"
    research_id: str
    sub_question_id: str
    text: str = ""
    status: str = "pending"
    source_count: int = 0


class ResearchSearchCompletedEvent(SessionEvent):
    """A search round completed across parallel searchers."""

    event_type: str = "research.search.completed"
    research_id: str
    iteration: int = 0
    sources_found: int = 0
    new_findings: int = 0
    cost_usd: float = 0.0


class ResearchCoverageEvent(SessionEvent):
    """Coverage ratio updated after analyst evaluation."""

    event_type: str = "research.coverage.updated"
    research_id: str
    iteration: int = 0
    coverage_ratio: float = 0.0
    gaps_remaining: int = 0
    stop_reason: str = ""


class ResearchSynthesizingEvent(SessionEvent):
    """Report synthesis is about to start."""

    event_type: str = "research.synthesizing"
    research_id: str
    total_findings: int = 0
    findings_after_compression: int = 0


class ResearchCompletedEvent(SessionEvent):
    """Research loop completed successfully."""

    event_type: str = "research.completed"
    research_id: str
    report_title: str = ""
    total_sources: int = 0
    total_iterations: int = 0
    coverage_ratio: float = 0.0
    verification_score: float | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


class ResearchFailedEvent(SessionEvent):
    """Research loop failed with an error."""

    event_type: str = "research.failed"
    research_id: str
    error: str = ""
    iteration: int = 0
    cost_usd: float = 0.0


# =============================================================================
# Event Type Registry
# =============================================================================


EVENT_TYPE_MAP: dict[str, type[SessionEvent]] = {
    "mission.narrative": MissionNarrativeEvent,
    "mission.artifact.found": MissionArtifactFoundEvent,
    "mission_plan.refined": MissionPlanRefinedEvent,
    "mission_plan.task.status_changed": MissionPlanTaskStatusChangedEvent,
    "mission_plan.gate_mode_changed": MissionPlanGateModeChangedEvent,
    "user.message.sent": UserMessageEvent,
    "user.approval.granted": UserApprovalEvent,
    "agent.thinking.started": AgentThinkingEvent,
    "agent.tool.called": AgentToolCallEvent,
    "agent.tool.returned": AgentToolResultEvent,
    "agent.response.chunk": AgentResponseChunkEvent,
    "agent.response.complete": AgentResponseCompleteEvent,
    "agent.approval.requested": ApprovalRequestedEvent,
    "approval.response.received": ApprovalResponseEvent,
    "plan.phase": PlanningPhaseEvent,
    "plan.created": PlanCreatedEvent,
    "plan.step.started": PlanStepStartedEvent,
    "plan.step.completed": PlanStepCompletedEvent,
    "plan.revised": PlanRevisedEvent,
    "session.cost.updated": CostUpdateEvent,
    "workflow.run.started": WorkflowRunStartedEvent,
    "workflow.execution.started": WorkflowExecutionStartedEvent,
    "workflow.execution.completed": WorkflowExecutionCompletedEvent,
    "workflow.run.completed": WorkflowRunCompletedEvent,
    "workflow.run.failed": WorkflowRunFailedEvent,
    "workflow.condition.evaluated": WorkflowConditionEvaluatedEvent,
    "workflow.notification.sent": WorkflowNotificationSentEvent,
    "workflow.tool_call.completed": WorkflowToolCallCompletedEvent,
    "workflow.llm_call.completed": WorkflowLlmCallCompletedEvent,
    "workflow.branch.passed": WorkflowBranchPassedEvent,
    "workflow.merge.completed": WorkflowMergeCompletedEvent,
    "workflow.sub_workflow.completed": WorkflowSubWorkflowCompletedEvent,
    "workflow.decision.resolved": WorkflowDecisionResolvedEvent,
    "workflow.step.skipped": WorkflowStepSkippedEvent,
    "workflow.human_input.requested": WorkflowHumanInputRequestedEvent,
    "workflow.human_input.responded": WorkflowHumanInputRespondedEvent,
    "workflow.graph.updated": WorkflowGraphEvent,
    "convergence.iteration": ConvergenceIterationEvent,
    "convergence.completed": ConvergenceCompletedEvent,
    "convergence.verification": FinalVerificationEvent,
    "system.info": SystemEvent,
    "system.execution.created": SystemExecutionCreatedEvent,
    "system.execution.completed": SystemExecutionCompletedEvent,
    "system.budget.warning": SystemBudgetWarningEvent,
    "system.session.created": SystemSessionCreatedEvent,
    "mission_plan.supervisor_decision": SupervisorDecisionEmittedEvent,
    "knowledge.intent.revised": MissionIntentRevisedEvent,
    "knowledge.learning.extracted": MissionLearningExtractedEvent,
    "knowledge.learning.promoted": PlatformLearningPromotedEvent,
    "knowledge.contradiction.flagged": LearningContradictionFlaggedEvent,
    # Research events (Plan 40)
    "research.started": ResearchStartedEvent,
    "research.decomposed": ResearchDecomposedEvent,
    "research.subquestion.updated": ResearchSubQuestionUpdatedEvent,
    "research.search.completed": ResearchSearchCompletedEvent,
    "research.coverage.updated": ResearchCoverageEvent,
    "research.synthesizing": ResearchSynthesizingEvent,
    "research.completed": ResearchCompletedEvent,
    "research.failed": ResearchFailedEvent,
    # Mission runs and schedules (Plan 88)
    "mission_run.created": MissionRunCreatedEvent,
    "mission_run.status_changed": MissionRunStatusChangedEvent,
    "mission_run.occurrence_recorded": MissionRunOccurrenceRecordedEvent,
    "mission_schedule.changed": MissionScheduleChangedEvent,
    "mission_schedule.sync_failed": MissionScheduleSyncFailedEvent,
    "task.failed": TaskFailedEvent,
    "context.compacted": ContextCompactedEvent,
}


def deserialize_event(data: dict) -> SessionEvent | None:
    """
    Deserialize a dict into the correct SessionEvent subclass.

    Looks up event_type in the registry. Falls back to base SessionEvent
    for unknown types. Returns None if data is invalid.

    Args:
        data: Dictionary with event fields including event_type.

    Returns:
        Typed SessionEvent instance, or None if deserialization fails.
    """
    event_type = data.get("event_type")
    if not event_type:
        logger.warning("Missing event_type in event data", extra={"data_keys": list(data.keys())})
        return None

    event_cls = EVENT_TYPE_MAP.get(event_type, SessionEvent)
    try:
        return event_cls(**data)
    except Exception:
        # non-critical — this IS the event deserialization path; there is
        # no event system left to report a broken event through. Caller
        # (subscribe_mission) skips a None and keeps streaming.
        logger.warning(
            "Failed to deserialize event",
            extra={"event_type": event_type},
            exc_info=True,
        )
        return None
