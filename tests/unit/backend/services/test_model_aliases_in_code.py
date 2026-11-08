"""Code that needs "a cheap model" names an alias, never a provider:model string."""

from modules.backend.core.config import get_app_config
from modules.backend.services.synthesis import _MODEL_ALIAS


def test_the_synthesis_service_uses_a_configured_alias():
    assert _MODEL_ALIAS in get_app_config().models.aliases
