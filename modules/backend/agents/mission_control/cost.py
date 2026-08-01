"""Cost calculation for agent executions.

Pricing comes from mission_control.yaml model_pricing config.
Budget enforcement lives in SessionService — this module only computes costs.
"""

from modules.backend.agents.mission_control.middleware import _load_mission_control_config
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def compute_cost_usd(
    input_tokens: int,
    output_tokens: int,
    model: str | None = None,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    thinking_tokens: int = 0,
) -> float:
    """Compute dollar cost from token counts and model pricing config.

    All rates read from config/agents/mission_control.yaml model_pricing.
    Cache and thinking token params default to 0 for backward compatibility.
    """
    config = _load_mission_control_config()
    default_rates = config.model_pricing.get("default")
    rates = config.model_pricing.get(model or "")
    if rates is None:
        if default_rates is None:
            raise ValueError(
                f"No pricing config found for model '{model}' and no 'default' "
                "entry exists in config/agents/mission_control.yaml model_pricing — "
                "add one or the other. Returning 0.0 would silently defeat budget "
                "enforcement."
            )
        logger.warning(
            "No pricing config for model, using 'default' rates — add a "
            "model_pricing entry to stop seeing this warning",
            extra={"model": model},
        )
        rates = default_rates

    input_cost = (input_tokens / 1_000_000) * rates.input
    output_cost = ((output_tokens + thinking_tokens) / 1_000_000) * rates.output
    cache_read_cost = (cache_read_tokens / 1_000_000) * rates.cache_read
    cache_write_5m_cost = (cache_write_5m_tokens / 1_000_000) * rates.cache_write_5m
    cache_write_1h_cost = (cache_write_1h_tokens / 1_000_000) * rates.cache_write_1h

    return round(
        input_cost + output_cost + cache_read_cost + cache_write_5m_cost + cache_write_1h_cost,
        6,
    )


def estimate_cost(
    estimated_input_tokens: int,
    model: str | None = None,
) -> float:
    """Estimate cost before execution. Conservative: assumes output = 30% of input."""
    estimated_output = int(estimated_input_tokens * 0.3)
    return compute_cost_usd(estimated_input_tokens, estimated_output, model)
