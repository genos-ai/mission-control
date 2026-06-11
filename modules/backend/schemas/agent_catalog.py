"""
Agent Catalog API Schemas.

Request/response models for the agent catalog endpoints.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCatalogResponse(BaseModel):
    """List-view response for a catalog agent."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: str
    agent_type: str
    version: str
    description: str
    enabled: bool
    chat_enabled: bool = False
    visibility: str
    keywords: list[str]
    tools: list[str]
    model_config_json: dict[str, Any]
    scope: dict[str, Any]
    engine: str = "pydantic_ai"
    effort: str | None = None


class AgentCatalogDetailResponse(BaseModel):
    """Full detail response for a catalog agent."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: str
    agent_type: str
    version: str
    description: str
    system_prompt: str
    model_config_json: dict[str, Any]
    tools: list[str]
    scope: dict[str, Any]
    interface: dict[str, Any] | None
    constraints: dict[str, Any]
    keywords: list[str]
    enabled: bool
    chat_enabled: bool = False
    visibility: str
    engine: str = "pydantic_ai"
    effort: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentCatalogCreateRequest(BaseModel):
    """Admin request to create a catalog entry."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(
        ..., min_length=1, max_length=200,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
    )
    agent_type: str = Field(
        ..., pattern=r"^(vertical|horizontal|system)$",
    )
    version: str = Field(default="1.0.0", max_length=20)
    description: str = Field(..., min_length=1, max_length=2000)
    system_prompt: str = Field(default="")
    model_config_json: dict[str, Any] = Field(
        ..., description='{"name": "anthropic:model", "temperature": 0.0, "max_tokens": 4096}',
    )
    tools: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(
        default_factory=lambda: {"read": [], "write": []},
    )
    interface: dict[str, Any] | None = None
    constraints: dict[str, Any] = Field(
        default_factory=lambda: {
            "timeout_seconds": 120,
            "cost_ceiling_usd": 1.0,
            "retry_budget": 2,
        },
    )
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
    visibility: str = Field(
        default="public", pattern=r"^(public|system)$",
    )


class SystemPromptUpdateRequest(BaseModel):
    """Request to update an agent's system prompt."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)
    changed_by: str = Field(..., min_length=1, max_length=200)
    change_reason: str | None = Field(None, max_length=1000)
