"""
DEPRECATED: Import from modules.backend.tools instead.

This file is a backward-compatibility re-export. The canonical
tool implementation now lives in modules/backend/tools/ (Plan 65).
"""

from modules.backend.tools.query_knowledge import query_knowledge as knowledge_query

__all__ = ["knowledge_query"]
