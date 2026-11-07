"""
Catalog YAML sync schemas.

Typed result of comparing the agent catalog in the database with the
config/agents/**/agent.yaml files that seed it.
"""

from typing import Any

from pydantic import BaseModel


class FieldChange(BaseModel):
    """One YAML field that differs from the database.

    ``field`` is the dotted YAML path (``model.name``, ``scope.read``). The YAML
    value is the effective one, so a key that is absent shows its default.
    """

    field: str
    yaml_value: Any
    database_value: Any


class AgentDrift(BaseModel):
    """An agent whose YAML file disagrees with its catalog row."""

    agent_name: str
    path: str
    changes: list[FieldChange]


class SyncFailure(BaseModel):
    """An agent whose YAML file cannot be brought in line, and why."""

    agent_name: str
    path: str
    reason: str


class YamlSyncReport(BaseModel):
    """Drift between the catalog and the agent YAML files.

    ``database_only`` agents (created through the admin API) have no YAML file,
    and ``yaml_only`` files have no catalog row yet. Neither is drift: sync edits
    existing files and never creates or deletes one.
    """

    drifted: list[AgentDrift]
    failures: list[SyncFailure]
    in_sync: int
    database_only: list[str]
    yaml_only: list[str]

    @property
    def clean(self) -> bool:
        """True when every agent's YAML matches the catalog."""
        return not (self.drifted or self.failures)
