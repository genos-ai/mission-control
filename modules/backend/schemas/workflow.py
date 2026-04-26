"""
Workflow YAML validation schemas.

Validates workflow structure, step definitions, trigger configuration,
budget limits, output mapping, and context declarations. Used by
WorkflowService at load time to reject invalid workflows early (P5: Fail Fast).

Each step becomes an Execution at runtime. The output_mapping on each step
defines the anti-corruption layer for inter-execution data flow.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkflowOutputFieldMapping(BaseModel):
    """Maps a field from an ExecutionOutcome task result to a named context key."""

    model_config = ConfigDict(extra="forbid")

    source_task: str = Field(
        ...,
        description="Task ID within the ExecutionOutcome whose output to extract from",
    )
    source_field: str = Field(
        ...,
        description="Field name within the task's output_data to extract",
    )
    target_key: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Context key name for downstream missions",
    )


class WorkflowStepOutputMapping(BaseModel):
    """Output mapping for a workflow step.

    Defines which fields from the step's ExecutionOutcome are extracted
    and made available to downstream steps. This is the anti-corruption
    layer — downstream executions only see curated context, never raw
    ExecutionOutcome internals.
    """

    model_config = ConfigDict(extra="forbid")

    summary_key: str | None = Field(
        None,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Store ExecutionOutcome.result_summary under this context key",
    )
    field_mappings: list[WorkflowOutputFieldMapping] = Field(
        default_factory=list,
        description="Extract specific fields from ExecutionOutcome task results",
    )


class WorkflowEdgeSchema(BaseModel):
    """A visual edge in the workflow graph (React Flow)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique edge ID, e.g. 'step-a->step-b'")
    source: str = Field(..., description="Source node (step) ID")
    target: str = Field(..., description="Target node (step) ID")
    source_handle: str = Field(default="output")
    target_handle: str = Field(default="input")
    label: str | None = Field(None, description="Optional edge label")


class ConditionConfig(BaseModel):
    """Configuration for a condition node."""

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(..., min_length=1, max_length=500)
    true_label: str = Field(default="Yes")
    false_label: str = Field(default="No")


class NotificationConfig(BaseModel):
    """Configuration for a notification node."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(default="telegram", pattern=r"^(telegram|sse)$")
    message_template: str = Field(..., min_length=1, max_length=2000)
    recipient: str | None = None


class HumanInputConfig(BaseModel):
    """Configuration for a human_input node — durable pause until a human responds."""

    model_config = ConfigDict(extra="forbid")

    prompt_message: str = Field(..., min_length=1, max_length=2000)
    channel: str = Field(default="telegram", pattern=r"^(telegram|sse|chat)$")
    timeout_hours: float | None = Field(None, ge=0.1, le=720)
    default_response: str | None = Field(None, max_length=2000)
    choices: list[str] | None = None


class WorkflowStepSchema(BaseModel):
    """A single step in a workflow.

    Each step becomes an Execution with its own Mission Control instance.
    Non-agent node types (condition, notification) are executed inline by the
    wave engine without creating an Execution record.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    description: str | None = Field(None, max_length=500)
    node_type: str = Field(
        default="agent_step",
        pattern=r"^(agent_step|condition|notification|human_input)$",
    )
    capability: str | None = Field(
        None,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
    )
    condition_config: ConditionConfig | None = None
    notification_config: NotificationConfig | None = None
    human_input_config: HumanInputConfig | None = None
    roster: str = Field(
        default="default",
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    complexity_tier: str = Field(
        default="simple",
        pattern=r"^(simple|complex)$",
    )
    cost_ceiling_usd: float | None = Field(None, ge=0.01)
    environment: str = Field(
        default="local",
        pattern=r"^(local|worktree|container|sandbox|auto)$",
    )
    input: dict[str, Any] = Field(default_factory=dict)
    output_mapping: WorkflowStepOutputMapping | None = None
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(None, ge=10, le=86400)
    max_refinement_rounds: int = Field(
        default=1, ge=1,
        description="Max internal retry/QA cycles per step. 1 = no retry.",
    )
    termination: str = Field(
        default="completion",
        pattern=r"^(completion|budget_exhausted|criteria_met|max_iterations)$",
        description="Step termination mode",
    )
    max_iterations: int | None = Field(
        None, ge=1,
        description="For termination=max_iterations: how many internal cycles",
    )

    @model_validator(mode="after")
    def _validate_node_type_config(self) -> "WorkflowStepSchema":
        if self.node_type == "agent_step" and not self.capability:
            raise ValueError("capability is required for agent_step nodes")
        if self.node_type == "condition" and self.condition_config is None:
            raise ValueError("condition_config is required for condition nodes")
        if self.node_type == "notification" and self.notification_config is None:
            raise ValueError("notification_config is required for notification nodes")
        if self.node_type == "human_input" and self.human_input_config is None:
            raise ValueError("human_input_config is required for human_input nodes")
        return self


class WorkflowTriggerSchema(BaseModel):
    """How and when the workflow is triggered."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        default="on_demand",
        pattern=r"^(on_demand|schedule|event)$",
    )
    schedule: str | None = None
    event_type: str | None = None
    match_patterns: list[str] = Field(default_factory=list)


class WorkflowBudgetSchema(BaseModel):
    """Cost constraints for workflow execution."""

    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float = Field(default=10.00, ge=0.01)
    max_tokens: int | None = Field(None, ge=1000)


class WorkflowObjectiveSchema(BaseModel):
    """Strategic business outcome for the workflow."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(..., min_length=1, max_length=1000)
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    owner: str = Field(..., min_length=1, max_length=200)
    priority: str = Field(..., pattern=r"^(critical|high|normal|low)$")
    regulatory_reference: str | None = Field(None, max_length=500)


class WorkflowSchema(BaseModel):
    """Root schema for a workflow YAML file."""

    model_config = ConfigDict(extra="forbid")

    workflow_name: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_-]*)*\.workflow$",
        description="Unique workflow identifier. Convention: {domain}.{name}.workflow",
    )
    description: str = Field(..., min_length=1, max_length=1000)
    objective: WorkflowObjectiveSchema
    version: int = Field(default=1, ge=1)
    enabled: bool = True
    mission_name: str | None = Field(
        None,
        description="Human-readable mission name (display only, not used for resolution).",
    )
    trigger: WorkflowTriggerSchema = Field(default_factory=WorkflowTriggerSchema)
    budget: WorkflowBudgetSchema = Field(default_factory=WorkflowBudgetSchema)
    context: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStepSchema] = Field(..., min_length=1)

    @field_validator("steps")
    @classmethod
    def validate_steps(
        cls, steps: list[WorkflowStepSchema],
    ) -> list[WorkflowStepSchema]:
        """Validate step IDs are unique, deps exist, no cycles."""
        step_ids = {step.id for step in steps}

        # Duplicate IDs
        if len(step_ids) != len(steps):
            seen: set[str] = set()
            dupes = []
            for step in steps:
                if step.id in seen:
                    dupes.append(step.id)
                seen.add(step.id)
            raise ValueError(f"Duplicate step IDs: {dupes}")

        # Dependencies reference existing steps
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(
                        f"Step '{step.id}' depends on '{dep_id}' "
                        f"which does not exist"
                    )

        # Self-dependencies
        for step in steps:
            if step.id in step.depends_on:
                raise ValueError(f"Step '{step.id}' depends on itself")

        # Cycle detection (Kahn's algorithm)
        in_degree: dict[str, int] = {s.id: 0 for s in steps}
        graph: dict[str, list[str]] = {s.id: [] for s in steps}
        for step in steps:
            for dep_id in step.depends_on:
                graph[dep_id].append(step.id)
                in_degree[step.id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        sorted_count = 0
        while queue:
            node = queue.pop(0)
            sorted_count += 1
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if sorted_count != len(steps):
            raise ValueError("Workflow steps contain a dependency cycle")

        # Output mapping target key uniqueness
        target_keys: list[str] = []
        for step in steps:
            if step.output_mapping:
                if step.output_mapping.summary_key:
                    target_keys.append(step.output_mapping.summary_key)
                for fm in step.output_mapping.field_mappings:
                    target_keys.append(fm.target_key)
        if len(target_keys) != len(set(target_keys)):
            raise ValueError(
                "Duplicate output mapping target keys in workflow steps"
            )

        return steps


# =============================================================================
# API Response Schemas
# =============================================================================


class WorkflowListResponse(BaseModel):
    """API response for listing available workflows."""

    workflow_name: str
    description: str
    version: int
    enabled: bool
    trigger_type: str
    step_count: int
    budget_usd: float
    objective_category: str
    objective_priority: str
    objective_owner: str


class WorkflowDetailResponse(BaseModel):
    """API response for a single workflow with full details."""

    workflow_name: str
    description: str
    objective: WorkflowObjectiveSchema
    version: int
    enabled: bool
    trigger: WorkflowTriggerSchema
    budget: WorkflowBudgetSchema
    context_keys: list[str]
    steps: list[WorkflowStepSchema]
