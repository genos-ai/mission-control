"""Model backends: which providers exist and which wire protocols each one speaks.

A provider is where a model is hosted and how we authenticate to it
(providers.yaml). A protocol is how we talk to it. They are separate because
one provider can serve models over several protocols: Foundry serves GPT and
DeepSeek over OpenAI chat completions and Claude over the Anthropic Messages
API, behind one resource, one credential and one firewall rule.

``BACKENDS`` is the only place that knows both. The registry (models.yaml)
records each model's protocol, ``_build_model`` looks it up there, and this table
supplies the builder. Supporting a new protocol on a provider is one builder
function and one entry here.

Builders import their SDKs inside the function so loading this module, which the
config schema does, stays cheap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from modules.backend.schemas.agent_config import AgentModelSchema

OPENAI_CHAT = "openai_chat"
ANTHROPIC_MESSAGES = "anthropic_messages"
COPILOT_SDK = "copilot_sdk"

# Protocols that pass response_format (JSON-schema strict mode) through to the model.
NATIVE_OUTPUT_PROTOCOLS = frozenset({OPENAI_CHAT})

# Protocols that take Anthropic cache-control and thinking settings.
ANTHROPIC_SETTINGS_PROTOCOLS = frozenset({ANTHROPIC_MESSAGES})

ModelBuilder = Callable[[str, "str | AgentModelSchema"], "Model"]


def _openai_profile(bare_name: str, config_model: str | AgentModelSchema):
    """Return a ModelProfile that pins structured-output mode, or None for defaults.

    Lets an agent opt in to native JSON-schema output (``output_mode: native``).
    Azure gpt-4.1 accepts response_format json_schema strict=true on the wire, and
    a profile override unlocks that path through PydanticAI.

    Built on PydanticAI's own factory (``openai_model_profile``) rather than the
    OpenAIModelProfile dataclass, because the factory fills in OpenAI defaults the
    dataclass leaves None:
      - supports_json_schema_output=True (the actual unlock)
      - json_schema_transformer=OpenAIJsonSchemaTransformer (rewrites Pydantic
        schemas to OpenAI strict-mode shape: additionalProperties=false, all
        fields required, no $ref; without it complex output types fail at request
        submission)
      - openai_supports_strict_tool_definition, supported_builtin_tools, etc.
    Only ``default_structured_output_mode`` is patched, via dataclasses.replace.

    Returns None for a bare string (no opt-in possible) and for output_mode
    "tool", so PydanticAI's per-model defaults apply unchanged.
    """
    from modules.backend.schemas.agent_config import AgentModelSchema

    if not isinstance(config_model, AgentModelSchema) or config_model.output_mode == "tool":
        return None

    import dataclasses

    from pydantic_ai.profiles.openai import openai_model_profile

    base = openai_model_profile(bare_name)
    return dataclasses.replace(base, default_structured_output_mode=config_model.output_mode)


def _anthropic_direct(bare_name: str, config_model: str | AgentModelSchema) -> Model:
    from pydantic_ai.models.anthropic import AnthropicModel

    from modules.backend.core.model_providers import get_anthropic_provider

    return AnthropicModel(bare_name, provider=get_anthropic_provider())


def _anthropic_on_foundry(bare_name: str, config_model: str | AgentModelSchema) -> Model:
    from pydantic_ai.models.anthropic import AnthropicModel

    from modules.backend.core.model_providers import get_foundry_anthropic_provider

    return AnthropicModel(bare_name, provider=get_foundry_anthropic_provider())


def _openai_direct(bare_name: str, config_model: str | AgentModelSchema) -> Model:
    from pydantic_ai.models.openai import OpenAIModel

    from modules.backend.core.model_providers import get_openai_provider

    return OpenAIModel(bare_name, provider=get_openai_provider())


def _openai_on_foundry(bare_name: str, config_model: str | AgentModelSchema) -> Model:
    from pydantic_ai.models.openai import OpenAIModel

    from modules.backend.core.model_providers import get_foundry_provider

    return OpenAIModel(
        bare_name,
        provider=get_foundry_provider(),
        profile=_openai_profile(bare_name, config_model),
    )


def _copilot(bare_name: str, config_model: str | AgentModelSchema) -> Model:
    from modules.backend.core.copilot_model import CopilotModel

    return CopilotModel(model_id=bare_name)


BACKENDS: dict[str, dict[str, ModelBuilder]] = {
    "anthropic": {ANTHROPIC_MESSAGES: _anthropic_direct},
    "openai": {OPENAI_CHAT: _openai_direct},
    "copilot": {COPILOT_SDK: _copilot},
    "foundry": {
        OPENAI_CHAT: _openai_on_foundry,
        ANTHROPIC_MESSAGES: _anthropic_on_foundry,
    },
}
