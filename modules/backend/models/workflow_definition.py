"""
Workflow Definition Model.

DB-stored workflow definitions. Each row is a named workflow recipe
belonging to a mission, containing the step graph, trigger config,
budget limits, and objective metadata.

System workflow templates have mission_id=NULL.
"""

from datetime import datetime

from sqlalchemy import DateTime, JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class WorkflowDefinition(UUIDMixin, TimestampMixin, Base):
    """A stored workflow definition."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "mission_id", "name",
            name="uq_workflow_definitions_mission_name",
        ),
    )

    mission_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL for system templates",
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    objective: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment='WorkflowObjectiveSchema: {statement, category, owner, priority}',
    )
    steps: Mapped[list] = mapped_column(
        JSON, nullable=False,
        comment="Array of WorkflowStepSchema dicts",
    )
    edges_json: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="React Flow edges derived from steps[].depends_on",
    )
    canvas_state: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="Viewport + node positions for the visual editor",
    )
    trigger_config: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment='WorkflowTriggerSchema: {type, schedule, event_type, match_patterns}',
    )
    budget_config: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment='WorkflowBudgetSchema: {max_cost_usd, max_tokens}',
    )
    parameters: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="WorkflowParameterSchema[]: typed user-facing inputs shown before run",
    )
    context: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="Static context data passed to all steps",
    )
    designed_by: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="architect:<agent_id> or user:<user_id>",
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the user confirmed the workflow",
    )

    @property
    def trigger_type(self) -> str:
        """Extract trigger type from trigger_config JSON."""
        return (self.trigger_config or {}).get("type", "on_demand")

    @property
    def step_count(self) -> int:
        """Number of steps in this workflow."""
        return len(self.steps or [])

    def __repr__(self) -> str:
        return (
            f"<WorkflowDefinition(name={self.name!r}, "
            f"mission={self.mission_id}, v={self.version})>"
        )
