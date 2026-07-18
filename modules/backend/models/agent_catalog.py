"""
Agent Catalog Model.

The global agent registry. Each row represents a registered agent with its
system prompt, model configuration, tools, filesystem scope, interface
contract, and execution constraints.

Seeded from config/agents/**/agent.yaml + config/prompts/agents/**/system.md
on first run. After seeding, the database is the source of truth.
"""

from sqlalchemy import JSON, Boolean, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class AgentCatalog(UUIDMixin, TimestampMixin, Base):
    """A registered agent in the global catalog."""

    __tablename__ = "agent_catalog"

    agent_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        index=True,
    )
    agent_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="vertical, horizontal, or system",
    )
    version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="1.0.0",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Locked system prompt (sysadmin only)",
    )
    model_config_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment='{"name": "anthropic:model", "temperature": 0.0, "max_tokens": 4096}',
    )
    tools: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        comment="Array of tool identifiers",
    )
    scope: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment='{"read": [...], "write": [...]}',
    )
    interface: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment='{"input": {"field": "type"}, "output": {"field": "type"}}',
    )
    constraints: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment='{"timeout_seconds": 120, "cost_ceiling_usd": 1.0, "retry_budget": 2}',
    )
    keywords: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        comment="Array of capability keywords for routing",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    chat_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether this agent supports conversational chat",
    )
    visibility: Mapped[str] = mapped_column(
        String(20),
        default="public",
        nullable=False,
        index=True,
        comment="public (all users) or system (sysadmins only)",
    )
    engine: Mapped[str] = mapped_column(
        String(20),
        default="pydantic_ai",
        nullable=False,
        comment="Execution engine: pydantic_ai, claude_code, codex, copilot",
    )
    effort: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Effort level for CLI engines (low/medium/high)",
    )
    # Fields needed for registry to work from DB (Plan 59)
    invocation_tier: Mapped[str] = mapped_column(
        String(20),
        default="user",
        nullable=False,
        comment="Invocation tier: user, platform, system",
    )
    invocation_required_role: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Required role for invocation (e.g. admin for platform agents)",
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20),
        default="standard",
        nullable=False,
        comment="Execution mode: standard, local, worktree, container",
    )
    thinking_budget_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment='{"max_thinking_tokens": 10000}',
    )
    max_input_length: Mapped[int] = mapped_column(
        default=32000,
        nullable=False,
        comment="Maximum input length in characters",
    )
    max_budget_usd: Mapped[float] = mapped_column(
        Numeric(12, 6, asdecimal=False),
        default=1.0,
        nullable=False,
        comment="Per-agent budget ceiling in USD",
    )
    cache_ttl: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Cache TTL for Anthropic prompt caching: 5m or 1h (None = cost.yaml default)",
    )
    produces_artifact: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="When true, persistence layer creates a mission_artifact from this agent's output",
    )
    artifact_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Artifact type: research_report, vulnerability_report, quality_audit",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentCatalog(name={self.agent_name!r}, "
            f"type={self.agent_type}, enabled={self.enabled})>"
        )
