"""
DEPRECATED: Import from modules.backend.tools instead.

This file is a backward-compatibility re-export. The canonical
tool implementations now live in modules/backend/tools/ (Plan 65).
"""

from modules.backend.tools.apply_fix import apply_fix
from modules.backend.tools.run_tests import run_tests

__all__ = ["apply_fix", "run_tests"]
