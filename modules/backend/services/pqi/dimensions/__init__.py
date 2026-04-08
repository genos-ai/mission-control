"""PQI dimension scorers — re-exports for backwards compatibility."""

from modules.backend.services.pqi.dimensions.analysis import (
    score_maintainability,
    score_modularity,
    score_security,
    score_testability,
)
from modules.backend.services.pqi.dimensions.style import (
    score_elegance,
    score_reusability,
    score_robustness,
)

__all__ = [
    "score_elegance",
    "score_maintainability",
    "score_modularity",
    "score_reusability",
    "score_robustness",
    "score_security",
    "score_testability",
]
