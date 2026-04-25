"""
DEPRECATED: Import from modules.backend.tools instead.

This file is a backward-compatibility re-export. The canonical
tool implementations now live in modules/backend/tools/ (one file
per tool, verb_noun naming convention — Plan 65).
"""

from modules.backend.tools.fetch_url import fetch_url as fetch_and_extract
from modules.backend.tools.search_codebase import search_codebase
from modules.backend.tools.search_web import search_web as web_search

__all__ = ["web_search", "fetch_and_extract", "search_codebase"]
