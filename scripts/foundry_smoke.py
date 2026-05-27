"""Foundry provider smoke test — run before flipping any agent.

Exercises the production factory get_foundry_provider() against the live
Foundry deployment. Tests:
  1. Structured output via tool mode (the P17 default)
  2. Tool calls
  3. Streaming
  4. Cost attribution (proves the pricing row beats cost.py's silent fallback)
  5. Native structured output via ModelProfile override (advisory)

Tests 1-4 are mandatory; the process exits non-zero if any fails. Test 5 is
advisory — its result dictates whether the §4.4 _build_profile helper and §4.5
output_mode field ship in Phase 1 (see Plan 82 §3.2 gate).

Reads endpoint + auth from config/settings/providers.yaml.

Usage:
    az login  # if not already
    python scripts/foundry_smoke.py --verbose
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Make modules.* imports work when invoked directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import click  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.openai import OpenAIModel  # noqa: E402
from pydantic_ai.profiles import ModelProfile  # noqa: E402

from modules.backend.agents.mission_control.cost import compute_cost_usd  # noqa: E402
from modules.backend.core.logging import get_logger  # noqa: E402
from modules.backend.core.model_providers import get_foundry_provider  # noqa: E402

logger = get_logger(__name__)


class PersonInfo(BaseModel):
    name: str
    age: int
    occupation: str


async def _run(deployment: str) -> int:
    """Return exit code: 0 if Tests 1-4 pass, 1 otherwise. Test 5 is advisory."""
    provider = get_foundry_provider()
    advisory_failures: list[str] = []

    # Test 1: structured output via PydanticAI's final_result tool path (default).
    tool_model = OpenAIModel(deployment, provider=provider)
    agent = Agent(tool_model, output_type=PersonInfo)
    result = await agent.run("Jane Doe is a 42-year-old risk analyst.")
    assert result.output.name == "Jane Doe", f"got {result.output.name!r}"
    assert result.output.age == 42, f"got {result.output.age}"
    logger.info("PASS Test 1 structured output (tool mode): %s", result.output)

    # Test 2: tool call.
    tool_agent = Agent(tool_model)

    @tool_agent.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    r2 = await tool_agent.run("Use the add tool to compute 17 + 25.")
    assert "42" in r2.output, f"output missing '42': {r2.output!r}"
    logger.info("PASS Test 2 tool call: %s", r2.output)

    # Test 3: streaming — must yield at least one non-empty chunk.
    chunks: list[str] = []
    async with tool_agent.run_stream("Say 'hello' once.") as stream:
        async for chunk in stream.stream_text():
            chunks.append(chunk)
    assert chunks, "stream yielded zero chunks"
    joined = "".join(chunks).strip()
    assert joined, "stream produced only empty text"
    logger.info("PASS Test 3 streaming: %d chunks, %d chars", len(chunks), len(joined))

    # Test 4: cost attribution — proves the pricing row is wired correctly.
    # If this matches the 'default' fallback rate, cost.py is silently
    # misattributing and the pricing row is missing or misnamed.
    usage = result.usage()
    model_key = f"foundry:{deployment}"
    cost = compute_cost_usd(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model=model_key,
        cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or 0,
    )
    default_cost = compute_cost_usd(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model="__nonexistent__",  # forces the silent default-rate fallback
    )
    cached = getattr(usage, "cache_read_tokens", None)
    logger.info(
        "USAGE: input=%d output=%d cached=%s cost=$%.6f default_fallback=$%.6f",
        usage.input_tokens,
        usage.output_tokens,
        cached,
        cost,
        default_cost,
    )
    assert cost > 0, f"cost is zero — pricing row missing for {model_key!r}"
    assert cost != default_cost, (
        f"cost equals the default-rate fallback (${default_cost:.6f}); "
        f"pricing row for {model_key!r} is not being picked up by compute_cost_usd"
    )
    logger.info("PASS Test 4 cost attribution: $%.6f for %s", cost, model_key)

    # Test 5 (ADVISORY): native structured output via PydanticAI's default profile.
    # This is the EXACT production path — _build_model() would construct the Model
    # the same way when an agent sets output_mode: native. Originally failed because
    # PydanticAI's built-in profile for gpt-4.1 sets supports_json_schema_output=False.
    # Tests 6 and 7 (below) probe whether that gate is correct.
    try:
        native_model = OpenAIModel(
            deployment,
            provider=provider,
            profile=ModelProfile(default_structured_output_mode="native"),
        )
        native_agent = Agent(native_model, output_type=PersonInfo)
        r5 = await native_agent.run("Bob Lee is a 29-year-old chef.")
        assert r5.output.name == "Bob Lee", f"got {r5.output.name!r}"
        assert r5.output.age == 29, f"got {r5.output.age}"
        logger.info("PASS Test 5 (advisory) native via default profile: %s", r5.output)
    except Exception as exc:
        advisory_failures.append(f"Test 5 (PydanticAI default profile): {exc}")
        logger.warning("ADVISORY FAIL Test 5: %s", exc)

    # Test 6 (DIAGNOSTIC): bypass PydanticAI entirely. Hit Azure's chat.completions
    # directly with response_format json_schema strict=true. This isolates the
    # question: does the deployment ACCEPT native JSON-schema mode at the wire
    # level, or is the limit purely PydanticAI's profile classification?
    sdk_client = provider.client  # AsyncOpenAI built by get_foundry_provider()
    person_schema = {
        "name": "PersonInfo",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "occupation": {"type": "string"},
            },
            "required": ["name", "age", "occupation"],
            "additionalProperties": False,
        },
    }
    try:
        raw = await sdk_client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "Extract structured fields from the user text."},
                {"role": "user", "content": "Carol Ng is a 35-year-old data engineer."},
            ],
            response_format={"type": "json_schema", "json_schema": person_schema},
        )
        import json
        payload = json.loads(raw.choices[0].message.content)
        person = PersonInfo.model_validate(payload)
        assert person.name == "Carol Ng", f"got {person.name!r}"
        assert person.age == 35, f"got {person.age}"
        logger.info("PASS Test 6 (diagnostic) wire-level native JSON: %s", person)
        wire_native_ok = True
    except Exception as exc:
        advisory_failures.append(f"Test 6 (wire-level native): {exc}")
        logger.warning("ADVISORY FAIL Test 6 wire-level: %s", exc)
        wire_native_ok = False

    # Test 7 (DIAGNOSTIC): if Test 6 worked, the deployment supports native JSON
    # at the wire level — so PydanticAI's gate is wrong. Override the profile's
    # supports_json_schema_output and try the same path Test 5 took.
    if wire_native_ok:
        try:
            override_profile = ModelProfile(
                default_structured_output_mode="native",
                supports_json_schema_output=True,
            )
            override_model = OpenAIModel(deployment, provider=provider, profile=override_profile)
            override_agent = Agent(override_model, output_type=PersonInfo)
            r7 = await override_agent.run("Dave Patel is a 51-year-old surgeon.")
            assert r7.output.name == "Dave Patel", f"got {r7.output.name!r}"
            assert r7.output.age == 51, f"got {r7.output.age}"
            logger.info("PASS Test 7 (diagnostic) native via overridden profile: %s", r7.output)
        except Exception as exc:
            advisory_failures.append(f"Test 7 (forced PydanticAI native): {exc}")
            logger.warning("ADVISORY FAIL Test 7 overridden profile: %s", exc)
    else:
        logger.info("SKIP Test 7 (wire-level didn't work — no point trying PydanticAI override)")

    if advisory_failures:
        logger.warning("Advisory failures: %s", advisory_failures)
    return 0


@click.command()
@click.option(
    "--deployment",
    default=lambda: os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
    help="Foundry deployment name (defaults to $AZURE_OPENAI_DEPLOYMENT or 'gpt-4.1').",
)
@click.option("--verbose", is_flag=True, help="INFO-level logging.")
@click.option("--debug", is_flag=True, help="DEBUG-level logging.")
def main(deployment: str, verbose: bool, debug: bool) -> None:
    """Foundry provider smoke test. Exits 0 if Tests 1-4 pass; Test 5 is advisory."""
    level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s — %(message)s")
    sys.exit(asyncio.run(_run(deployment)))


if __name__ == "__main__":
    main()
