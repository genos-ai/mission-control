"""
Foundry Bing Grounding search provider.

Calls the project-scoped Foundry Responses API with the `web_search` tool
(Grounding with Bing Search backend). Results are reconstructed from the
model's `url_citation` annotations into the same SearchResult shape used
by perplexity / tavily / brave.

Auth, endpoint, and AAD token plumbing all flow through
`get_foundry_project_provider()` — this service does not manage credentials.

Pricing: Grounding with Bing Search bills $14 / 1,000 transactions against
the Bing resource attached to the Foundry project, plus model tokens for
the synthesising model. The Bing connection is provisioned and attached
at the Foundry project level; this code does not reference it directly.

The `web_search` tool does not support include / exclude domain filters —
those kwargs are accepted for provider-interface parity and silently
ignored. Switch to bing_custom_search for domain restriction (separate
provider, not implemented here).
"""

from __future__ import annotations

from typing import Any

from modules.backend.core.logging import get_logger
from modules.backend.core.model_providers import get_foundry_project_provider
from modules.backend.schemas.research import SearchResult

logger = get_logger(__name__)

# Hardcoded for now — these are Foundry-side knobs, not per-call ones.
# Promote to providers.yaml / a search.yaml file when more than one
# caller needs to vary them.
#
# Model alternatives in the Foundry project (see config/settings/models.yaml):
#   gpt-5.4     — top capability, higher cost (current default for synthesis quality)
#   gpt-5-mini  — balanced cost/quality
#   gpt-5-nano  — cheapest, lowest latency
#   gpt-4.1     — older generation, kept for compatibility
_SEARCH_MODEL = "gpt-5.4"
_SEARCH_CONTEXT_SIZE = "medium"  # one of: low, medium, high

_VALID_CONTEXT_SIZES = {"low", "medium", "high"}


class FoundryBingGroundingSearch:
    """Web search via Foundry Responses API + web_search (Bing Grounding) tool."""

    def __init__(
        self,
        *,
        model: str = _SEARCH_MODEL,
        context_size: str = _SEARCH_CONTEXT_SIZE,
    ) -> None:
        self._model = model
        size = (context_size or "medium").lower()
        self._context_size = size if size in _VALID_CONTEXT_SIZES else "medium"
        # The provider factory returns a bare AsyncOpenAI configured for
        # the project-scoped Foundry endpoint, with AAD token refresh
        # managed by azure.identity.aio.get_bearer_token_provider().
        self._client = get_foundry_project_provider()

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Run a Bing-grounded search via the Foundry Responses API.

        `search_depth`, `include_domains`, and `exclude_domains` are
        accepted for parity with other providers but ignored — the
        `web_search` tool exposes only `search_context_size`.
        """
        # The OpenAI Python SDK's .responses.create() POSTs to
        #   {base_url}/responses
        # which against the project-scoped Foundry base_url becomes
        #   https://<account>.services.ai.azure.com/api/projects/<project>/openai/v1/responses
        # — the documented Foundry web_search invocation path.
        response = await self._client.responses.create(
            model=self._model,
            input=query,
            tools=[{
                "type": "web_search",
                "search_context_size": self._context_size,
            }],
            tool_choice="required",
        )

        # response is a pydantic model — convert to dict for the parser
        # (mirrors what `.json()` would produce on the underlying HTTP body).
        data: dict[str, Any] = response.model_dump()
        results = _parse_response(data, max_results=max_results)
        logger.info(
            "Foundry Bing Grounding search complete",
            extra={
                "query": query[:80],
                "results": len(results),
                "model": self._model,
                "context_size": self._context_size,
            },
        )
        return results


def _parse_response(data: dict, *, max_results: int) -> list[SearchResult]:
    """Reconstruct SearchResult list from a Responses API payload.

    The Responses API returns one or more `message` items under `output`,
    each with `output_text` content blocks. URL citations are attached as
    annotations on those content blocks; start / end indices are used to
    slice the surrounding text as the snippet for each citation.
    """
    summary_text = ""
    citations: list[dict] = []

    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") != "output_text":
                continue
            text = part.get("text") or ""
            if text and not summary_text:
                summary_text = text
            for ann in part.get("annotations") or []:
                if ann.get("type") == "url_citation":
                    citations.append(ann)

    seen_urls: set[str] = set()
    results: list[SearchResult] = []
    for i, ann in enumerate(citations):
        url = (ann.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        snippet = _snippet_from_annotation(ann, summary_text)
        results.append(SearchResult(
            url=url,
            title=ann.get("title") or url,
            snippet=snippet[:500],
            content=snippet,
            relevance_score=max(0.0, 1.0 - i * 0.05),
            provider="foundry-bing-grounding",
        ))
        if len(results) >= max_results:
            break

    return results


def _snippet_from_annotation(ann: dict, summary_text: str) -> str:
    start = ann.get("start_index")
    end = ann.get("end_index")
    if (
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(summary_text)
    ):
        sliced = summary_text[start:end].strip()
        if sliced:
            return sliced
    return summary_text[:500].strip()
