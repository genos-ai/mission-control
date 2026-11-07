"""
Model provider schemas.

Typed results for ModelProviderService: the provider/model inventory and the
outcome of a live ping.
"""

from typing import Literal

from pydantic import BaseModel

CredentialStatus = Literal["present", "missing", "not_checked"]


class ProviderModel(BaseModel):
    """One model of a provider, with where it is used."""

    name: str
    qualified_name: str
    registered: bool
    agents: list[str]
    aliases: list[str]


class ProviderInfo(BaseModel):
    """One provider: how it authenticates and which models it serves."""

    provider: str
    auth_mode: str | None
    credential_env_var: str | None
    credential: CredentialStatus
    base_url: str | None
    models: list[ProviderModel]


class ProviderListing(BaseModel):
    """Every provider known to the registry, providers.yaml, agents or aliases."""

    providers: list[ProviderInfo]
    agents_without_model: list[str]


class ModelPingResult(BaseModel):
    """Outcome of one live model call."""

    model: str
    ok: bool
    elapsed_ms: float
    error: str | None
    error_type: str | None


class ModelPingReport(BaseModel):
    """Outcome of pinging a set of models."""

    ok: bool
    results: list[ModelPingResult]


class ProviderSwitchChange(BaseModel):
    """One agent's model rewritten by a provider switch."""

    agent_name: str
    current_model: str
    new_model: str
    new_config: dict


class DiscoveredModel(BaseModel):
    """A model a provider reports as available to call.

    ``name`` is the identifier the provider reports. ``aliases`` are other names
    that address the same model (Anthropic accepts an undated alias for a dated
    snapshot id), so a registry entry or an agent may use either. ``model`` is the
    underlying model, or its display name where the provider has no separate
    deployment. Fields a provider does not report are None.
    """

    name: str
    model: str
    format: str
    version: str | None
    sku: str | None
    state: str | None
    created: str | None = None
    aliases: list[str] = []


class DeployedModel(DiscoveredModel):
    """A discovered model set against the registry and the agent catalogue."""

    registered: bool
    agents: list[str]


class MissingModel(BaseModel):
    """A registry model the provider does not report, with the agents that use it."""

    name: str
    agents: list[str]


class ProtocolMismatch(BaseModel):
    """A registry model filed under a protocol its deployment cannot be called over."""

    name: str
    registered: str
    expected: str
    agents: list[str]


class ProviderDiscovery(BaseModel):
    """What a provider offers now, compared with the registry."""

    provider: str
    models: list[DeployedModel]
    not_deployed: list[MissingModel]
    protocol_mismatches: list[ProtocolMismatch] = []
    unmapped_formats: list[str] = []
