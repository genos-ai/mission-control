"""
Model Provider Service.

Answers two questions about the LLM providers: what exists (registry, auth,
which agents and aliases use each model) and does it work (a live one-token
call per model). Read-only: it never changes the catalog or the config.
"""

import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.preflight import preflight_check
from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ProvidersSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.model_builder import _resolve_model_alias
from modules.backend.core.model_discovery import discover_models
from modules.backend.core.model_providers import credential_status
from modules.backend.schemas.model_provider import (
    DeployedModel,
    DiscoveredModel,
    MissingModel,
    ModelPingReport,
    ModelPingResult,
    ProtocolMismatch,
    ProviderDiscovery,
    ProviderInfo,
    ProviderListing,
    ProviderModel,
    ProviderSwitchChange,
)
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _provider_of(qualified_name: str, source: str) -> str:
    """Provider prefix of a ``provider:model`` string; raises when there is none."""
    if ":" not in qualified_name:
        raise ValidationError(f"{source}: '{qualified_name}' is not a 'provider:model' string")
    return qualified_name.split(":", 1)[0]


class ModelProviderService(BaseService):
    """Inventory and liveness checks for the LLM providers."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._catalog = AgentCatalogService(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["ModelProviderService", None]:
        """Create a ModelProviderService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield ModelProviderService(db)

    async def list_providers(self) -> ProviderListing:
        """Every provider and model, with auth state and agent and alias usage."""
        config = get_app_config()
        registry = config.models.models_by_provider()

        agents_by_model, agents_without_model = await self._agents_by_model()

        aliases_by_model: dict[str, list[str]] = {}
        for alias, target in config.models.aliases.items():
            _provider_of(target, f"alias {alias}")
            aliases_by_model.setdefault(target, []).append(alias)

        provider_names = (
            set(registry)
            | set(ProvidersSchema.model_fields)
            | {_provider_of(q, "agent model") for q in agents_by_model}
            | {_provider_of(q, "alias target") for q in aliases_by_model}
        )

        providers = [
            self._describe(name, registry.get(name, []), agents_by_model, aliases_by_model)
            for name in sorted(provider_names)
        ]
        return ProviderListing(
            providers=providers,
            agents_without_model=sorted(agents_without_model),
        )

    async def discover(self, provider: str) -> ProviderDiscovery:
        """What ``provider`` offers now, set against the registry and the agents."""
        discovered = await discover_models(provider)
        agents_by_model, _ = await self._agents_by_model()
        config = get_app_config()
        comparison = self.compare_discovery(
            provider,
            discovered,
            registered=config.models.models_of(provider),
            agents_by_model=agents_by_model,
        )
        deployment_protocols = getattr(config.providers, provider).deployment_protocols
        mismatches = self.find_protocol_mismatches(
            provider,
            discovered,
            registered_protocols={
                model: config.models.spec_of(provider, model).protocol
                for model in config.models.models_of(provider)
            },
            deployment_protocols=deployment_protocols,
            agents_by_model=agents_by_model,
        )
        return comparison.model_copy(
            update={
                "protocol_mismatches": mismatches,
                "unmapped_formats": self.find_unmapped_formats(discovered, deployment_protocols),
            }
        )

    @staticmethod
    def find_protocol_mismatches(
        provider: str,
        discovered: list[DiscoveredModel],
        *,
        registered_protocols: dict[str, str],
        deployment_protocols: dict[str, str],
        agents_by_model: dict[str, list[str]],
    ) -> list[ProtocolMismatch]:
        """Registry models filed under a protocol their deployment cannot speak.

        ``deployment_protocols`` (providers.yaml) maps the format the provider
        reports for a deployment to the protocol it answers. A Claude deployment
        registered under ``openai_chat`` passes every config check and then fails
        on its first call, so it is reported here instead. A deployment whose
        format has no mapping cannot be checked; see ``find_unmapped_formats``.
        """
        mismatches = []
        for model in discovered:
            expected = deployment_protocols.get(model.format)
            if expected is None:
                continue
            for name in (model.name, *model.aliases):
                registered = registered_protocols.get(name)
                if registered is not None and registered != expected:
                    mismatches.append(
                        ProtocolMismatch(
                            name=name,
                            registered=registered,
                            expected=expected,
                            agents=sorted(agents_by_model.get(f"{provider}:{name}", [])),
                        )
                    )
        return mismatches

    @staticmethod
    def find_unmapped_formats(
        discovered: list[DiscoveredModel], deployment_protocols: dict[str, str]
    ) -> list[str]:
        """Deployment formats with no entry in deployment_protocols, so they go unchecked."""
        return sorted({m.format for m in discovered} - set(deployment_protocols))

    @staticmethod
    def compare_discovery(
        provider: str,
        discovered: list[DiscoveredModel],
        *,
        registered: list[str],
        agents_by_model: dict[str, list[str]],
    ) -> ProviderDiscovery:
        """Set discovered models against the registry and the agents using them.

        ``not_deployed`` is the dangerous half: registry models the provider no
        longer reports, with the agents that would fail on them.
        """

        def agents_of(names: list[str]) -> list[str]:
            return sorted(
                agent for name in names for agent in agents_by_model.get(f"{provider}:{name}", [])
            )

        offered = {name for m in discovered for name in (m.name, *m.aliases)}
        return ProviderDiscovery(
            provider=provider,
            models=[
                DeployedModel(
                    **m.model_dump(),
                    registered=bool({m.name, *m.aliases} & set(registered)),
                    agents=agents_of([m.name, *m.aliases]),
                )
                for m in discovered
            ],
            not_deployed=[
                MissingModel(name=name, agents=agents_of([name]))
                for name in registered
                if name not in offered
            ],
        )

    async def ping(
        self,
        *,
        models: list[str],
        providers: list[str],
        all_models: bool,
    ) -> ModelPingReport:
        """Make one live call per selected model.

        Selection is ``models`` (``provider:model`` or an alias), plus every
        registry model of each of ``providers``, or every registry model with
        ``all_models``. Every selected model must be in the registry; nothing is
        called until the whole selection has validated.
        """
        if not (models or providers or all_models):
            raise ValidationError("Select at least one model, one provider, or all models to ping.")

        registry = get_app_config().models.models_by_provider()
        selected: list[str] = []

        if all_models:
            providers = list(registry)
        for provider in providers:
            if provider not in registry:
                raise ValidationError(
                    f"Provider '{provider}' is not in the model registry. "
                    f"Known providers: {sorted(registry)}."
                )
            selected.extend(f"{provider}:{model}" for model in registry[provider])

        for model in models:
            qualified = _resolve_model_alias(model)
            provider = _provider_of(qualified, "model")
            if qualified.split(":", 1)[1] not in registry.get(provider, []):
                raise ValidationError(
                    f"Model '{qualified}' is not in the model registry "
                    "(config/settings/models.yaml)."
                )
            selected.append(qualified)

        selected = list(dict.fromkeys(selected))
        logger.info("Model ping requested", extra={"models": selected})

        result = await preflight_check(models=selected)
        return ModelPingReport(
            ok=result.ok,
            results=[
                ModelPingResult(
                    model=check.model_name,
                    ok=check.ok,
                    elapsed_ms=round(check.elapsed_ms, 1),
                    error=check.error,
                    error_type=check.error_type,
                )
                for check in result.checks
            ],
        )

    async def _agents_by_model(self) -> tuple[dict[str, list[str]], list[str]]:
        """Agent names by the qualified model they use, and agents naming no model."""
        agents_by_model: dict[str, list[str]] = {}
        agents_without_model: list[str] = []
        for entry in await self._catalog.list_catalog(enabled_only=False):
            name = entry.model_config_json.get("name")
            if not name:
                agents_without_model.append(entry.agent_name)
                continue
            qualified = _resolve_model_alias(name)
            _provider_of(qualified, f"agent {entry.agent_name}")
            agents_by_model.setdefault(qualified, []).append(entry.agent_name)
        return agents_by_model, agents_without_model

    @staticmethod
    def parse_model_map(raw: str | None) -> dict[str, str]:
        """Parse ``old=new,old=new`` (bare model names) into a dict."""
        if not raw:
            return {}
        model_map: dict[str, str] = {}
        for pair in raw.split(","):
            old, sep, new = pair.strip().partition("=")
            if not (sep and old.strip() and new.strip()):
                raise ValidationError(f"Malformed model map entry '{pair}'; expected old=new.")
            model_map[old.strip()] = new.strip()
        return model_map

    async def plan_switch(
        self,
        *,
        provider: str,
        model_map: dict[str, str],
    ) -> list[ProviderSwitchChange]:
        """Work out the model rewrite that moves every agent onto ``provider``.

        Each agent's model keeps its bare name when the target registry has it,
        else maps by ``model_map``, else by a name that matches ignoring
        punctuation (``claude-opus-4-6`` and ``claude-opus-4.6``). Anything else
        is a problem. All problems are reported together and nothing is planned
        unless there are none, so a switch never half-applies.
        """
        models_config = get_app_config().models
        if provider not in models_config.registry:
            raise ValidationError(
                f"Provider '{provider}' is not in the model registry. "
                f"Known providers: {sorted(models_config.registry)}."
            )
        target_models = models_config.models_of(provider)
        for old, new in model_map.items():
            if new not in target_models:
                raise ValidationError(
                    f"Model map target '{new}' (for '{old}') is not a {provider} registry model. "
                    f"Registry: {target_models}."
                )

        changes: list[ProviderSwitchChange] = []
        problems: list[str] = []
        for entry in await self._catalog.list_catalog(enabled_only=False):
            current = entry.model_config_json.get("name")
            if not current:
                problems.append(f"{entry.agent_name}: no model name")
                continue
            if ":" not in current:
                problems.append(
                    f"{entry.agent_name}: uses the alias '{current}'; "
                    "change the alias with 'catalog aliases set'"
                )
                continue
            current_provider, bare = current.split(":", 1)
            if current_provider == provider:
                continue

            new_bare = self._target_model(bare, target_models, model_map)
            if new_bare is None:
                problems.append(f"{entry.agent_name}: no {provider} model for '{current}'")
                continue
            changes.append(
                ProviderSwitchChange(
                    agent_name=entry.agent_name,
                    current_model=current,
                    new_model=f"{provider}:{new_bare}",
                    new_config={**entry.model_config_json, "name": f"{provider}:{new_bare}"},
                )
            )

        if problems:
            raise ValidationError(
                f"Cannot switch to '{provider}'; nothing was changed.\n  "
                + "\n  ".join(problems)
                + "\nSupply the missing mappings with --model-map old=new."
            )
        return changes

    @staticmethod
    def _target_model(bare: str, target_models: list[str], model_map: dict[str, str]) -> str | None:
        """The target-registry model for ``bare``, or None when there is no single match.

        Map keys and registry names are compared ignoring punctuation, so
        ``claude-opus-4-6`` also covers ``claude-opus-4.6``.
        """

        def squash(name: str) -> str:
            return re.sub(r"[^a-z0-9]", "", name.lower())

        mapped = {squash(old): new for old, new in model_map.items()}
        if squash(bare) in mapped:
            return mapped[squash(bare)]
        if bare in target_models:
            return bare

        matches = [m for m in target_models if squash(m) == squash(bare)]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _describe(
        provider: str,
        registered_models: list[str],
        agents_by_model: dict[str, list[str]],
        aliases_by_model: dict[str, list[str]],
    ) -> ProviderInfo:
        """Build one provider row from the registry, providers.yaml and usage."""
        in_use = [q.split(":", 1)[1] for q in agents_by_model if q.startswith(f"{provider}:")]
        in_use += [q.split(":", 1)[1] for q in aliases_by_model if q.startswith(f"{provider}:")]
        unregistered = sorted(set(in_use) - set(registered_models))

        models = [
            ProviderModel(
                name=name,
                qualified_name=f"{provider}:{name}",
                registered=name in registered_models,
                agents=sorted(agents_by_model.get(f"{provider}:{name}", [])),
                aliases=sorted(aliases_by_model.get(f"{provider}:{name}", [])),
            )
            for name in [*registered_models, *unregistered]
        ]

        auth = getattr(get_app_config().providers, provider, None)
        return ProviderInfo(
            provider=provider,
            auth_mode=auth.auth_mode if auth else None,
            credential_env_var=auth.env_var if auth else None,
            credential=credential_status(provider),
            base_url=auth.base_url if auth else None,
            models=models,
        )
