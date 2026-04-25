"""
DEPRECATED: Import from modules.backend.tools instead.

This file is a backward-compatibility re-export. The canonical
tool implementation now lives in modules/backend/tools/ (Plan 65).
"""

from modules.backend.tools.run_command import run_command

__all__ = ["run_command"]
