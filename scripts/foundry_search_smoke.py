"""Foundry Bing Grounding search smoke test — run before relying on web search.

Exercises the project-scoped Foundry Responses API with the `web_search` tool
(Grounding with Bing Search), end-to-end through Mission Control's plumbing.
Tests, in order:

  1. Provider factory — get_foundry_project_provider() builds an AsyncOpenAI
     client pointed at the project-scoped Foundry endpoint with AAD auth.
  2. Responses API — a direct client.responses.create() call with the
     web_search tool returns at least one url_citation annotation.
  3. Parser     — FoundryBingGroundingSearch parses the real response into
     SearchResult objects with non-empty URLs.
  4. End-to-end — WebSearchService picks foundry as the default provider and
     returns the same shape that search_web tool produces for an agent.

Reads endpoint + scope from config/settings/providers.yaml (foundry_project block).
Auth: AAD via DefaultAzureCredential (run `az login` first).

Default model is gpt-5.4 (top of the gpt-5 family registered in the project).
Override with --model to try gpt-5-mini / gpt-5-nano for cheaper/faster runs.

Usage:
    az login                                                  # if needed
    python scripts/foundry_search_smoke.py --verbose
    python scripts/foundry_search_smoke.py --model gpt-5-mini --verbose
    python scripts/foundry_search_smoke.py --query "your test query" --verbose
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Make modules.* imports work when invoked directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import click  # noqa: E402
import httpx  # noqa: E402

from modules.backend.core.config import get_app_config  # noqa: E402
from modules.backend.core.logging import get_logger  # noqa: E402
from modules.backend.core.model_providers import (  # noqa: E402
    close_foundry_credentials,
    get_foundry_project_provider,
)
from modules.backend.schemas.research import SearchResult  # noqa: E402
from modules.backend.services.search.bing_grounding_search import (  # noqa: E402
    FoundryBingGroundingSearch,
    _parse_response,
)
from modules.backend.services.search.web_search import WebSearchService  # noqa: E402

logger = get_logger(__name__)


# Topical query that should hit Bing's index reliably. The exact citations
# don't matter — we assert on structure (annotations present, URLs non-empty),
# not on specific content.
_DEFAULT_QUERY = "what is Microsoft Foundry"
_DEFAULT_MODEL = "gpt-5.4"

# Exit codes — pinned so CI can branch on them.
EXIT_OK = 0
EXIT_CONFIG_MISSING = 10
EXIT_PROVIDER_FACTORY_FAIL = 11
EXIT_RESPONSES_API_FAIL = 12
EXIT_NO_CITATIONS = 13
EXIT_PARSER_FAIL = 14
EXIT_END_TO_END_FAIL = 15


async def _run(model: str, query: str) -> int:
    # ── Test 1: Config + provider factory ─────────────────────────────────
    cfg = get_app_config().providers.foundry_project
    if not cfg.base_url:
        logger.error(
            "providers.foundry_project.base_url is empty — "
            "add the project-scoped Foundry endpoint to config/settings/providers.yaml",
        )
        return EXIT_CONFIG_MISSING
    logger.info("Project endpoint: %s", cfg.base_url)
    logger.info("AAD scope:        %s", cfg.scope)

    try:
        client = get_foundry_project_provider()
    except Exception as exc:
        logger.error("get_foundry_project_provider() failed: %s", exc)
        return EXIT_PROVIDER_FACTORY_FAIL

    base = str(client.base_url)
    assert base.startswith(cfg.base_url), f"client base_url mismatch: {base}"
    assert base.endswith("/openai/v1/"), f"missing /openai/v1/ suffix: {base}"
    logger.info("PASS Test 1 provider factory (client base_url=%s)", base)

    # ── Test 2: Responses API with web_search tool ────────────────────────
    logger.info("Calling Responses API with model=%s query=%r", model, query)
    try:
        resp = await client.responses.create(
            model=model,
            input=query,
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            tool_choice="required",
        )
    except Exception as exc:
        logger.error(
            "Responses API call failed (model=%s): %s",
            model,
            exc,
        )
        logger.error(
            "Common causes: model not deployed in this project, "
            "Bing Grounding connection missing on the project, "
            "or AAD token lacks data-plane access to the Foundry account.",
        )
        return EXIT_RESPONSES_API_FAIL

    payload = resp.model_dump()
    output_items = payload.get("output") or []
    if not output_items:
        logger.error("Responses API returned empty `output`: %s", payload)
        return EXIT_NO_CITATIONS

    found_citation = False
    summary_preview = ""
    for item in output_items:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and not summary_preview:
                summary_preview = (part.get("text") or "")[:200]
            for ann in part.get("annotations") or []:
                if ann.get("type") == "url_citation":
                    found_citation = True

    if not found_citation:
        logger.error(
            "Response had no url_citation annotations — the web_search tool "
            "did not fire. Check that the Bing Grounding connection is "
            "attached to the Foundry project.",
        )
        logger.error("Summary text: %s", summary_preview)
        return EXIT_NO_CITATIONS

    logger.info("PASS Test 2 Responses API web_search (got url_citation annotations)")
    if summary_preview:
        logger.info("  Summary preview: %s…", summary_preview)

    # ── Test 3: Parser handles the real response ──────────────────────────
    results = _parse_response(payload, max_results=10)
    if not results:
        logger.error("Parser produced zero results from a payload with citations")
        return EXIT_PARSER_FAIL

    for r in results:
        assert isinstance(r, SearchResult), f"non-SearchResult: {type(r)}"
        assert r.url, f"empty URL: {r}"
        assert r.provider == "foundry-bing-grounding", f"wrong provider: {r.provider}"

    logger.info("PASS Test 3 parser (%d SearchResult objects)", len(results))
    for r in results[:3]:
        logger.info(
            "  [score=%.2f] %s",
            r.relevance_score,
            r.title[:80],
        )
        logger.info("    URL: %s", r.url)
        if r.snippet:
            logger.info("    Snippet: %s…", r.snippet[:120])

    # ── Test 4: End-to-end via WebSearchService ───────────────────────────
    async with httpx.AsyncClient() as http_client:
        svc = WebSearchService(http_client)
        chosen = svc._default_provider()
        if chosen != "foundry":
            logger.error(
                "WebSearchService picked %r as default, not 'foundry'. "
                "Check providers.foundry_project.base_url in providers.yaml.",
                chosen,
            )
            return EXIT_END_TO_END_FAIL
        try:
            e2e = await svc.search(query, max_results=5)
        except Exception as exc:
            logger.error("WebSearchService.search() failed: %s", exc)
            return EXIT_END_TO_END_FAIL

    if not e2e:
        logger.error("WebSearchService returned zero results end-to-end")
        return EXIT_END_TO_END_FAIL
    if not all(r.provider == "foundry-bing-grounding" for r in e2e):
        logger.error(
            "Some results have non-foundry provider — fallback chain fired unexpectedly: %s",
            {r.provider for r in e2e},
        )
        return EXIT_END_TO_END_FAIL

    logger.info("PASS Test 4 end-to-end via WebSearchService (%d results)", len(e2e))

    logger.info("ALL_TESTS_PASS — Foundry Bing Grounding is wired up correctly.")
    return EXIT_OK


async def _main_async(model: str, query: str) -> int:
    """Run the test suite, then always close credentials so aiohttp sessions
    bound to the shared DefaultAzureCredential don't leak at process exit."""
    try:
        return await _run(model, query)
    finally:
        await close_foundry_credentials()


@click.command()
@click.option(
    "--model",
    default=_DEFAULT_MODEL,
    help=f"Foundry model deployment to use for synthesis (default: {_DEFAULT_MODEL}). "
    "Alternatives in the registry: gpt-5-mini, gpt-5-nano, gpt-4.1.",
)
@click.option(
    "--query",
    default=_DEFAULT_QUERY,
    help=f"Test query (default: {_DEFAULT_QUERY!r}).",
)
@click.option("--verbose", is_flag=True, help="INFO-level logging.")
@click.option("--debug", is_flag=True, help="DEBUG-level logging.")
def main(model: str, query: str, verbose: bool, debug: bool) -> None:
    """Foundry Bing Grounding smoke test. Exits 0 on success."""
    level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s — %(message)s")
    sys.exit(asyncio.run(_main_async(model, query)))


if __name__ == "__main__":
    main()
