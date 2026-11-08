"""Model discovery — ask a provider which models it offers right now.

Counterpart to model_providers.py (which builds clients to call models). Each
provider that can be queried has one function here returning DiscoveredModel
records; DISCOVERABLE_PROVIDERS is the single list of what is supported.

Anthropic lists the models its API serves, using the same client and key as
get_anthropic_provider().

Foundry lists deployments through Azure Resource Manager, not the model
endpoint: the deployment name is the ``model`` value requests must carry, and
the model endpoint is not reachable from every network the management plane is.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import ProviderAuthSchema
from modules.backend.core.exceptions import ExternalServiceError, ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.model_providers import (
    get_anthropic_provider,
    get_foundry_credential,
)
from modules.backend.schemas.model_provider import DiscoveredModel

logger = get_logger(__name__)


def _reason(exc: Exception) -> str:
    """The SDK's own message for a failed call, without its trailing full stop."""
    return str(getattr(exc, "message", None) or exc).rstrip(".")


async def discover_foundry_deployments(config: ProviderAuthSchema) -> list[DiscoveredModel]:
    """List the model deployments of the Foundry resource named in ``config``."""
    missing = [
        key
        for key in ("subscription_id", "resource_group", "account_name")
        if not getattr(config, key)
    ]
    if missing:
        raise ValidationError(
            f"Foundry discovery needs {', '.join(missing)} in the foundry block of "
            "config/settings/providers.yaml."
        )

    from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
    from azure.mgmt.cognitiveservices.aio import CognitiveServicesManagementClient

    logger.info(
        "Foundry discovery starting",
        extra={"resource_group": config.resource_group, "account": config.account_name},
    )
    try:
        async with CognitiveServicesManagementClient(
            get_foundry_credential(), config.subscription_id
        ) as client:
            deployments = [
                d async for d in client.deployments.list(config.resource_group, config.account_name)
            ]
    except (ClientAuthenticationError, HttpResponseError) as exc:
        raise ExternalServiceError(
            f"Could not list Foundry deployments for account '{config.account_name}': "
            f"{_reason(exc)}. Check 'az login' and Reader access on "
            f"resource group '{config.resource_group}'."
        ) from exc

    models = [
        DiscoveredModel(
            name=d.name,
            model=d.properties.model.name,
            format=d.properties.model.format,
            version=d.properties.model.version,
            sku=d.sku.name if d.sku else None,
            state=d.properties.provisioning_state,
        )
        for d in deployments
    ]
    models.sort(key=lambda m: m.name.lower())
    logger.info("Foundry discovery complete", extra={"deployments": len(models)})
    return models


# Anthropic reports a dated snapshot id such as claude-haiku-4-5-20251001; the same
# model is addressable by the id without the date suffix.
_DATED_SNAPSHOT = re.compile(r"^(?P<alias>.+)-\d{8}$")


def anthropic_aliases(model_id: str) -> list[str]:
    """Undated names that address the Anthropic snapshot ``model_id``."""
    match = _DATED_SNAPSHOT.match(model_id)
    return [match["alias"]] if match else []


def anthropic_format(deployment_protocols: dict[str, str]) -> str:
    """The format name Anthropic's own models carry, from providers.yaml.

    Anthropic's API lists only its own models, so ``providers.anthropic.
    deployment_protocols`` must name exactly one format: the label every model it
    lists gets. Requiring one keeps the label in config and rules out a guess.
    """
    if len(deployment_protocols) != 1:
        raise ValidationError(
            "providers.anthropic.deployment_protocols must name exactly one format, the one "
            f"Anthropic's own models carry (found {sorted(deployment_protocols) or 'none'})."
        )
    return next(iter(deployment_protocols))


def to_discovered_anthropic_model(info, format_name: str) -> DiscoveredModel:
    """Map the Anthropic SDK's ModelInfo to a DiscoveredModel of format ``format_name``."""
    return DiscoveredModel(
        name=info.id,
        model=info.display_name,
        format=format_name,
        version=None,
        sku=None,
        state=None,
        created=info.created_at.date().isoformat(),
        aliases=anthropic_aliases(info.id),
    )


async def discover_anthropic_models() -> list[DiscoveredModel]:
    """List the models the Anthropic API serves to the configured key."""
    from anthropic import APIConnectionError, APIStatusError

    format_name = anthropic_format(get_app_config().providers.anthropic.deployment_protocols)
    try:
        client = get_anthropic_provider().client
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    logger.info("Anthropic discovery starting")
    try:
        async with client:
            infos = [info async for info in client.models.list()]
    except (APIConnectionError, APIStatusError) as exc:
        raise ExternalServiceError(
            f"Could not list Anthropic models: {_reason(exc)}. "
            "Check the API key and network access to api.anthropic.com."
        ) from exc

    models = [to_discovered_anthropic_model(info, format_name) for info in infos]
    models.sort(key=lambda m: m.name.lower())
    logger.info("Anthropic discovery complete", extra={"models": len(models)})
    return models


_DISCOVERERS: dict[str, Callable[[], Awaitable[list[DiscoveredModel]]]] = {
    "anthropic": discover_anthropic_models,
    "foundry": lambda: discover_foundry_deployments(get_app_config().providers.foundry),
}

DISCOVERABLE_PROVIDERS = tuple(_DISCOVERERS)


async def discover_models(provider: str) -> list[DiscoveredModel]:
    """Models ``provider`` reports as available; raises if it cannot be queried."""
    if provider not in _DISCOVERERS:
        raise ValidationError(
            f"Discovery is not supported for '{provider}'. "
            f"Supported providers: {list(DISCOVERABLE_PROVIDERS)}."
        )
    return await _DISCOVERERS[provider]()
