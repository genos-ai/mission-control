"""DEPRECATED: Import from modules.backend.core.model_builder instead.

Re-exports for backward compatibility.
"""

from modules.backend.core.model_builder import (  # noqa: F401
    _build_model,
    _get_model_name,
    _resolve_model_alias,
    build_model_settings,
)

__all__ = ["_build_model", "_get_model_name", "_resolve_model_alias", "build_model_settings"]
