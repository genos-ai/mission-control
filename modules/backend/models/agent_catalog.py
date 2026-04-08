"""
Agent Catalog Model.

The global agent registry. Each row represents a registered agent with its
system prompt, model configuration, tools, filesystem scope, interface
contract, and execution constraints.

Seeded from config/agents/**/agent.yaml + config/prompts/agents/**/system.md
on first run. After seeding, the database is the source of truth.
"""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class AgentCatalog(UUIDMixin, TimestampMixin, Base):
    """A registered agent in the global catalog."""

    __tablename__ = "agent_catalog"

    agent_name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True,
    )
    agent_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="vertical, horizontal, or system",
    )
    version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0.0",
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="Locked system prompt (sysadmin only)",
    )
    model_config_json: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        comment='{"name": "anthropic:model", "temperature": 0.0, "max_tokens": 4096}',
    )
    tools: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="Array of tool identifiers",
    )
    scope: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment='{"read": [...], "write": [...]}',
    )
    interface: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='{"input": {"field": "type"}, "output": {"field": "type"}}',
    )
    constraints: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment='{"timeout_seconds": 120, "cost_ceiling_usd": 1.0, "retry_budget": 2}',
    )
    keywords: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="Array of capability keywords for routing",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True,
    )
    chat_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether this agent supports conversational chat",
    )
    visibility: Mapped[str] = mapped_column(
        String(20), default="public", nullable=False, index=True,
        comment="public (all users) or system (sysadmins only)",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentCatalog(name={self.agent_name!r}, "
            f"type={self.agent_type}, enabled={self.enabled})>"
        )
