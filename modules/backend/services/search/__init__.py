"""
Search services (Plan 40 §4).

Web search, content extraction, and codebase search for the deep
research system.
"""

from modules.backend.services.search.content_extract import ContentExtractService
from modules.backend.services.search.web_search import WebSearchService

__all__ = ["WebSearchService", "ContentExtractService"]
