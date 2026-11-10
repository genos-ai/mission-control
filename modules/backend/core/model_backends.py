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
    from pydantic_ai.profiles import ModelProfile

OPENAI_CHAT = "openai_chat"
ANTHROPIC_MESSAGES = "anthropic_messages"
COPILOT_SDK = "copilot_sdk"

# Protocols that pass response_format (JSON-schema strict mode) through to the model.
NATIVE_OUTPUT_PROTOCOLS = frozenset({OPENAI_CHAT})

# Protocols whose builder honours prompted output: the schema goes in the
# instructions and the answer comes back as JSON text, with no forced tool call.
# The Copilot builder takes no profile, so it is not listed.
PROMPTED_OUTPUT_PROTOCOLS = frozenset({OPENAI_CHAT, ANTHROPIC_MESSAGES})

# Structured-output modes that only some protocols can honour. 'tool' is absent
# because every protocol supports it.
OUTPUT_MODE_PROTOCOLS: dict[str, frozenset[str]] = {
    "native": NATIVE_OUTPUT_PROTOCOLS,
    "prompted": PROMPTED_OUTPUT_PROTOCOLS,
}


def output_mode_error(output_mode: str, protocols: set[str] | frozenset[str]) -> str | None:
    """Why none of ``protocols`` can honour ``output_mode``, or None when one can."""
    supporting = OUTPUT_MODE_PROTOCOLS.get(output_mode)
    if supporting is None or supporting & set(protocols):
        return None
    return f"output_mode='{output_mode}' requires one of the protocols {sorted(supporting)}"


# Protocols that take Anthropic cache-control and thinking settings.
ANTHROPIC_SETTINGS_PROTOCOLS = frozenset({ANTHROPIC_MESSAGES})

# A builder takes the bare model name and the structured-output mode in effect
# ('tool', 'native' or 'prompted'; _build_model decides which).
ModelBuilder = Callable[[str, str], "Model"]


def _with_output_mode(base: ModelProfile | None, output_mode: str) -> ModelProfile:
    """``base`` with only ``default_structured_output_mode`` replaced.

    Everything else the provider's factory filled in (JSON-schema transformer,
    strict-tool support, thinking tags) is kept.
    """
    import dataclasses

    from pydantic_ai.profiles import ModelProfile

    return dataclasses.replace(base or ModelProfile(), default_structured_output_mode=output_mode)


def _openai_profile(bare_name: str, output_mode: str) -> ModelProfile | None:
    """OpenAI-chat profile with the structured-output mode pinned, or None for 'tool'.

    Built on PydanticAI's own factory (``openai_model_profile``) rather than the
    OpenAIModelProfile dataclass, because the factory fills in OpenAI defaults the
    dataclass leaves None:
      - supports_json_schema_output=True (the unlock for 'native'; Azure gpt-4.1
        accepts response_format json_schema strict=true on the wire)
      - json_schema_transformer=OpenAIJsonSchemaTransformer (rewrites Pydantic
        schemas to OpenAI strict-mode shape: additionalProperties=false, all
        fields required, no $ref; without it complex output types fail at request
        submission)
      - openai_supports_strict_tool_definition, supported_builtin_tools, etc.

    'tool' is PydanticAI's own default, so None leaves the provider's profile as is.
    """
    if output_mode == "tool":
        return None

    from pydantic_ai.profiles.openai import openai_model_profile

    return _with_output_mode(openai_model_profile(bare_name), output_mode)


def _anthropic_profile(bare_name: str, output_mode: str) -> ModelProfile | None:
    """Anthropic-messages profile with the structured-output mode pinned, or None for 'tool'.

    'prompted' exists for models that reject a forced tool choice. PydanticAI's
    tool output mode sends ``tool_choice: {"type": "any"}`` whenever text output
    is not allowed, and Foundry's claude-sonnet-5-5 answers that with HTTP 400
    ("tool_choice: type "tool" and "any" are not supported for this model").
    Prompted mode allows text output, so tool_choice is 'auto' and the answer is
    JSON text validated against the output type.

    Starts from AnthropicProvider.model_profile rather than anthropic_model_profile:
    the provider's version adds AnthropicJsonSchemaTransformer, which the agent's
    function tools still need.
    """
    if output_mode == "tool":
        return None

    from pydantic_ai.providers.anthropic import AnthropicProvider

    return _with_output_mode(AnthropicProvider.model_profile(bare_name), output_mode)


def _anthropic_direct(bare_name: str, output_mode: str) -> Model:
    from pydantic_ai.models.anthropic import AnthropicModel

    from modules.backend.core.model_providers import get_anthropic_provider

    return AnthropicModel(
        bare_name,
        provider=get_anthropic_provider(),
        profile=_anthropic_profile(bare_name, output_mode),
    )


def _anthropic_on_foundry(bare_name: str, output_mode: str) -> Model:
    from pydantic_ai.models.anthropic import AnthropicModel

    from modules.backend.core.model_providers import get_foundry_anthropic_provider

    return AnthropicModel(
        bare_name,
        provider=get_foundry_anthropic_provider(),
        profile=_anthropic_profile(bare_name, output_mode),
    )


def _openai_direct(bare_name: str, output_mode: str) -> Model:
    from pydantic_ai.models.openai import OpenAIModel

    from modules.backend.core.model_providers import get_openai_provider

    return OpenAIModel(
        bare_name,
        provider=get_openai_provider(),
        profile=_openai_profile(bare_name, output_mode),
    )


def _openai_on_foundry(bare_name: str, output_mode: str) -> Model:
    from pydantic_ai.models.openai import OpenAIModel

    from modules.backend.core.model_providers import get_foundry_provider

    return OpenAIModel(
        bare_name,
        provider=get_foundry_provider(),
        profile=_openai_profile(bare_name, output_mode),
    )


def _copilot(bare_name: str, output_mode: str) -> Model:
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
