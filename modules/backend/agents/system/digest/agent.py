"""
Digest Agent — writes the narrative half of the end-of-run digest (Plan 88, 88.3.6).

Input is the deterministic digest draft, the mission objective and bounded
per-task output excerpts. Output is a DigestNarrative (summary, open items,
task headlines). An output validator rejects summaries over the configured
length, headlines over the configured length and any cited task id that is
not among the excerpts, so the model retries instead of storing bad output.

Called from the activity layer (88.3.7): the services layer must not import
agents, so the output type lives in schemas/run_memory.py.
"""

import json

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import RunUsage

from modules.backend.agents.mission_control.cost import compute_cost_usd
from modules.backend.agents.mission_control.helpers.cost_recorder import (
    extract_usage,
    record_llm_call,
)
from modules.backend.agents.mission_control.helpers.prompt_builder import assemble_instructions
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ExternalServiceError, ProviderError
from modules.backend.core.model_builder import (
    _build_model,
    _get_model_name,
    build_model_settings,
)
from modules.backend.schemas.agent_config import AgentConfigSchema
from modules.backend.schemas.run_memory import DigestNarrative


def _narrative_problems(
    output: DigestNarrative,
    *,
    task_ids: set[str],
    summary_max_chars: int,
    headline_max_chars: int,
) -> list[str]:
    """Every rule the narrative breaks; empty when it is acceptable."""
    problems = []
    if len(output.summary) > summary_max_chars:
        problems.append(
            f"summary is {len(output.summary)} characters; the limit is {summary_max_chars}"
        )
    for item in output.open_items:
        if item.source_task_id is not None and item.source_task_id not in task_ids:
            problems.append(f"open item cites unknown task id '{item.source_task_id}'")
    for headline in output.headlines:
        if headline.task_id not in task_ids:
            problems.append(f"headline cites unknown task id '{headline.task_id}'")
        if len(headline.headline) > headline_max_chars:
            problems.append(
                f"headline for task '{headline.task_id}' is {len(headline.headline)} "
                f"characters; the limit is {headline_max_chars}"
            )
    return problems


def _prompt(
    *,
    draft: dict,
    objective: str | None,
    task_excerpts: list[dict],
    summary_max_chars: int,
    headline_max_chars: int,
) -> str:
    return (
        f"Write the run digest narrative. Summary at most {summary_max_chars} characters; "
        f"each headline at most {headline_max_chars} characters. Cite only these task ids: "
        f"{[e['task_id'] for e in task_excerpts]}.\n\n"
        f"Mission objective:\n{objective or '(none stated)'}\n\n"
        f"Run facts (deterministic draft):\n{json.dumps(draft, default=str, indent=2)}\n\n"
        f"Task output excerpts:\n{json.dumps(task_excerpts, default=str, indent=2)}"
    )


async def _record_usage(
    usage: RunUsage,
    *,
    agent_config: AgentConfigSchema,
    agent_name: str,
    mission_id: str,
    mission_run_id: str,
    session_id: str,
) -> float:
    """Price ``usage``, write one llm_calls row attributed to the run, return the cost."""
    fields = extract_usage(usage)
    model_name = _get_model_name(agent_config.model)
    cost = compute_cost_usd(
        fields["input_tokens"],
        fields["output_tokens"],
        model_name,
        cache_read_tokens=fields["cache_read_tokens"],
        cache_write_1h_tokens=fields["cache_write_tokens"],
        thinking_tokens=fields["thinking_tokens"],
    )
    await record_llm_call(
        session_id=session_id,
        mission_id=mission_id,
        agent_name=agent_name,
        agent_role=agent_config.agent_type,
        model=model_name,
        usage=usage,
        cost_usd=cost,
        mission_run_id=mission_run_id,
        task_id=None,
    )
    return cost


async def generate_digest_narrative(
    *,
    draft: dict,
    objective: str | None,
    task_excerpts: list[dict],
    mission_id: str,
    mission_run_id: str,
    session_id: str,
) -> tuple[DigestNarrative, float]:
    """Run the digest agent once; return its output and the recorded cost in USD.

    Raises ExternalServiceError when the model fails or never produces valid
    output within the configured retries.
    """
    cfg = get_app_config().missions.digest
    agent_config = get_registry().get(cfg.agent_name)
    task_ids = {e["task_id"] for e in task_excerpts}

    agent: Agent[None, DigestNarrative] = Agent(
        _build_model(agent_config.model),
        instructions=assemble_instructions("system", "digest"),
        output_type=DigestNarrative,
        output_retries=cfg.agent_output_retries,
        model_settings=build_model_settings(agent_config),
    )

    @agent.output_validator
    def _validate(output: DigestNarrative) -> DigestNarrative:
        problems = _narrative_problems(
            output,
            task_ids=task_ids,
            summary_max_chars=cfg.summary_max_chars,
            headline_max_chars=cfg.headline_max_chars,
        )
        if problems:
            raise ModelRetry("Digest narrative rejected:\n- " + "\n- ".join(problems))
        return output

    prompt = _prompt(
        draft=draft,
        objective=objective,
        task_excerpts=task_excerpts,
        summary_max_chars=cfg.summary_max_chars,
        headline_max_chars=cfg.headline_max_chars,
    )
    # Usage accumulates here across retries so a failed run's billed tokens
    # are still recorded against the run (budget caps read llm_calls).
    usage = RunUsage()
    try:
        result = await agent.run(prompt, usage=usage)
    except (UnexpectedModelBehavior, ModelHTTPError, UsageLimitExceeded, ProviderError) as e:
        fields = extract_usage(usage)
        if fields["input_tokens"] or fields["output_tokens"]:
            await _record_usage(
                usage,
                agent_config=agent_config,
                agent_name=cfg.agent_name,
                mission_id=mission_id,
                mission_run_id=mission_run_id,
                session_id=session_id,
            )
        # Re-raised, not logged: the calling activity (88.3.7) owns the
        # deterministic fallback and its mission event.
        raise ExternalServiceError(f"digest agent failed: {type(e).__name__}") from e

    cost = await _record_usage(
        usage,
        agent_config=agent_config,
        agent_name=cfg.agent_name,
        mission_id=mission_id,
        mission_run_id=mission_run_id,
        session_id=session_id,
    )
    return result.output, cost
