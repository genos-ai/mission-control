"""
Unit Tests for mission_control/cost.py.

Tests exercise real config loading (model_pricing from mission_control.yaml).
"""

from modules.backend.agents.mission_control.cost import compute_cost_usd, estimate_cost


class TestComputeCostUsd:
    """Tests for compute_cost_usd()."""

    def test_zero_tokens(self):
        assert compute_cost_usd(0, 0, "anthropic:claude-haiku-4-5-20251001") == 0.0

    def test_known_model(self):
        cost = compute_cost_usd(1_000_000, 1_000_000, "anthropic:claude-haiku-4-5-20251001")
        assert cost > 0

    def test_unknown_model_uses_default(self):
        cost = compute_cost_usd(1_000_000, 1_000_000, "unknown:model")
        assert cost > 0

    def test_none_model_uses_default(self):
        cost = compute_cost_usd(1_000_000, 1_000_000, None)
        assert cost > 0

    def test_cost_scales_with_tokens(self):
        small = compute_cost_usd(1_000, 1_000)
        large = compute_cost_usd(1_000_000, 1_000_000)
        assert large > small

    def test_cost_precision(self):
        """Cost is rounded to 6 decimal places."""
        cost = compute_cost_usd(1, 1)
        decimals = str(cost).split(".")[-1] if "." in str(cost) else ""
        assert len(decimals) <= 6


class TestEstimateCost:
    """Tests for estimate_cost()."""

    def test_estimate_assumes_output_30pct_of_input(self):
        """estimate_cost(N, model) == compute_cost_usd(N, 0.3*N, model)."""
        estimated = estimate_cost(10_000, "anthropic:claude-haiku-4-5-20251001")
        computed = compute_cost_usd(10_000, 3_000, "anthropic:claude-haiku-4-5-20251001")
        assert estimated == computed

    def test_estimate_zero(self):
        assert estimate_cost(0) == 0.0


class TestCacheTokenCost:
    """Tests for cache and thinking token pricing (Plan 60)."""

    def test_cache_read_cheaper_than_input(self):
        """Cache reads should cost less than uncached input."""
        uncached = compute_cost_usd(10_000, 0, "anthropic:claude-sonnet-4-6")
        cached = compute_cost_usd(0, 0, "anthropic:claude-sonnet-4-6", cache_read_tokens=10_000)
        assert cached < uncached

    def test_cache_write_1h_more_expensive_than_input(self):
        """1h cache writes cost more than regular input (2x)."""
        input_cost = compute_cost_usd(10_000, 0, "anthropic:claude-sonnet-4-6")
        write_cost = compute_cost_usd(
            0, 0, "anthropic:claude-sonnet-4-6", cache_write_1h_tokens=10_000
        )
        assert write_cost > input_cost

    def test_thinking_tokens_billed_at_output_rate(self):
        """Thinking tokens are billed at the same rate as output tokens."""
        output_cost = compute_cost_usd(0, 10_000, "anthropic:claude-sonnet-4-6")
        thinking_cost = compute_cost_usd(
            0, 0, "anthropic:claude-sonnet-4-6", thinking_tokens=10_000
        )
        assert thinking_cost == output_cost

    def test_backward_compatible_defaults(self):
        """New params default to 0 — old callers get same result."""
        old_style = compute_cost_usd(1_000_000, 500_000, "anthropic:claude-sonnet-4-6")
        new_style = compute_cost_usd(
            1_000_000,
            500_000,
            "anthropic:claude-sonnet-4-6",
            cache_read_tokens=0,
            cache_write_1h_tokens=0,
            thinking_tokens=0,
        )
        assert old_style == new_style
