"""Preflight credit check — verify models have available credits before dispatch.

Provider-agnostic: uses _build_model() + PydanticAI so any supported provider
(Anthropic today, OpenAI/Bedrock tomorrow) goes through the same path.

Callable from CLI, API, or mission control — no rendering, just data.
"""

import asyncio
import time
from dataclasses import dataclass, field

from pydantic_ai import Agent, UsageLimits

from modules.backend.agents.mission_control.cost import compute_cost_usd
from modules.backend.agents.mission_control.helpers import _build_model, _get_model_name
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModelCheckResult:
    """Result of a single model ping."""

    model_name: str
    ok: bool
    elapsed_ms: float = 0.0
    error: str | None = None
    error_type: str | None = None


@dataclass
class PreflightResult:
    """Aggregate result of all model checks."""

    ok: bool = True
    checks: list[ModelCheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[ModelCheckResult]:
        return [c for c in self.checks if not c.ok]


async def _ping_model(model_name: str) -> ModelCheckResult:
    """Make a one-token call through PydanticAI to verify a model works."""
    start = time.monotonic()
    try:
        model = _build_model(model_name)
        agent: Agent[None, str] = Agent(model, output_type=str)
        await agent.run(
            "Reply with OK",
            usage_limits=UsageLimits(request_limit=1),
        )
        elapsed = (time.monotonic() - start) * 1000
        return ModelCheckResult(model_name=model_name, ok=True, elapsed_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        error_msg = str(e)
        error_type = "insufficient_credits" if "credit balance is too low" in error_msg.lower() else "error"
        return ModelCheckResult(
            model_name=model_name,
            ok=False,
            elapsed_ms=elapsed,
            error=error_msg,
            error_type=error_type,
        )


async def preflight_check(
    roster_name: str = "default",
    models: list[str] | None = None,
) -> PreflightResult:
    """Verify all models in a roster (or explicit list) have available credits.

    Args:
        roster_name: Roster to load and extract models from.
        models: Override — check these model strings instead of loading a roster.

    Returns:
        PreflightResult with per-model pass/fail.
    """
    if models is None:
        registry = get_registry()
        all_agents = registry.list_all()
        model_names = list({
            _get_model_name(registry.get(a["agent_name"]).model)
            for a in all_agents
        })
    else:
        model_names = list(set(models))

    model_names.sort()
    logger.info("Preflight check starting", extra={"models": model_names})

    tasks = [_ping_model(name) for name in model_names]
    checks = await asyncio.gather(*tasks)

    result = PreflightResult(checks=list(checks))
    result.ok = all(c.ok for c in checks)

    logger.info(
        "Preflight check complete",
        extra={"ok": result.ok, "models_checked": len(checks), "failures": len(result.failed)},
    )
    return result


# ---------------------------------------------------------------------------
# Per-agent ping — health check for a mission's roster
# ---------------------------------------------------------------------------


@dataclass
class AgentPingResult:
    """Result of a single agent ping."""

    agent_name: str
    model_name: str
    ok: bool
    elapsed_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


async def _ping_agent(agent_name: str, semaphore: asyncio.Semaphore) -> AgentPingResult:
    """Send a one-shot trivial prompt to an agent's configured model.

    Loads the model from the agent's catalog row via the registry, builds a
    minimal PydanticAI Agent, and invokes it with a fixed prompt. Skips tools
    and system prompt — the goal is to verify the model + provider + auth chain,
    not to exercise the agent's full machinery.
    """
    async with semaphore:
        start = time.monotonic()
        try:
            registry = get_registry()
            agent_config = registry.get(agent_name)
            if agent_config is None:
                return AgentPingResult(
                    agent_name=agent_name,
                    model_name="—",
                    ok=False,
                    error=f"agent '{agent_name}' not found in registry",
                )

            model_name = _get_model_name(agent_config.model)
            model = _build_model(agent_config.model)
            probe: Agent[None, str] = Agent(model, output_type=str)
            result = await probe.run(
                "Reply with OK",
                usage_limits=UsageLimits(request_limit=1),
            )
            elapsed = (time.monotonic() - start) * 1000

            usage = result.usage()
            input_tokens = usage.input_tokens or 0
            output_tokens = usage.output_tokens or 0
            cost = compute_cost_usd(input_tokens, output_tokens, model=model_name)

            return AgentPingResult(
                agent_name=agent_name,
                model_name=model_name,
                ok=True,
                elapsed_ms=elapsed,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            try:
                model_name = _get_model_name(registry.get(agent_name).model)
            except Exception:
                model_name = "—"
            return AgentPingResult(
                agent_name=agent_name,
                model_name=model_name,
                ok=False,
                elapsed_ms=elapsed,
                error=str(exc)[:400],
            )


async def ping_agents(
    agent_names: list[str],
    *,
    concurrency: int = 6,
) -> list[AgentPingResult]:
    """Ping every agent in `agent_names` in parallel, bounded by a semaphore.

    Returns results sorted by agent_name. Concurrency bound exists to respect
    provider rate limits when probing a large roster.
    """
    if not agent_names:
        return []
    semaphore = asyncio.Semaphore(max(1, concurrency))
    logger.info("Agent ping starting", extra={"agents": agent_names, "concurrency": concurrency})
    results = await asyncio.gather(*[_ping_agent(name, semaphore) for name in agent_names])
    results_list = list(results)
    results_list.sort(key=lambda r: r.agent_name)
    logger.info(
        "Agent ping complete",
        extra={
            "agents": len(results_list),
            "failures": sum(1 for r in results_list if not r.ok),
        },
    )
    return results_list
