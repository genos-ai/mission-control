"""PQI style dimensions — robustness, elegance, reusability.

These dimensions assess code style, type safety, and design quality.
"""

from __future__ import annotations

import statistics

from modules.backend.services.pqi.ast_analysis import ProjectAnalysis
from modules.backend.services.pqi.normalizers import (
    inverse_linear,
    ratio_score,
    sigmoid,
)
from modules.backend.services.pqi.tools import ToolResult
from modules.backend.services.pqi.types import DimensionScore


# ---------------------------------------------------------------------------
# 5. Robustness (weight: 0.13)
# ---------------------------------------------------------------------------


def score_robustness(project: ProjectAnalysis) -> DimensionScore:
    """Score robustness: type annotations, exception handling quality."""
    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]

    # Sub-metric: parameter type annotation coverage
    total_params = sum(f.total_params for f in source_files)
    annotated_params = sum(f.annotated_params for f in source_files)
    param_coverage = ratio_score(annotated_params, total_params)

    # Sub-metric: return type annotation coverage
    total_returns = sum(f.total_returns for f in source_files)
    annotated_returns = sum(f.annotated_returns for f in source_files)
    return_coverage = ratio_score(annotated_returns, total_returns)

    # Sub-metric: exception handling quality
    total_handlers = sum(f.exception_handlers for f in source_files)
    bare_excepts = sum(f.bare_excepts for f in source_files)
    broad_excepts = sum(f.broad_excepts for f in source_files)
    bad_handlers = bare_excepts + broad_excepts
    if total_handlers > 0:
        handler_quality = (1.0 - bad_handlers / total_handlers) * 100.0
    else:
        handler_quality = 100.0

    score = (
        param_coverage * 0.35
        + return_coverage * 0.30
        + handler_quality * 0.35
    )

    recommendations = []
    if param_coverage < 70:
        recommendations.append(f"Parameter type coverage is {param_coverage:.0f}% — add type annotations")
    if return_coverage < 70:
        recommendations.append(f"Return type coverage is {return_coverage:.0f}% — add return type annotations")
    if bare_excepts > 0:
        recommendations.append(f"{bare_excepts} bare/swallowed except clause(s) — catch specific exceptions")
    if broad_excepts > 0:
        recommendations.append(f"{broad_excepts} broad except(Exception) clause(s) — narrow the exception type")

    return DimensionScore(
        name="Robustness",
        score=score,
        sub_scores={
            "param_type_coverage": param_coverage,
            "return_type_coverage": return_coverage,
            "exception_handling_quality": handler_quality,
        },
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# 6. Elegance (weight: 0.12)
# ---------------------------------------------------------------------------


def score_elegance(
    project: ProjectAnalysis,
    tool_results: dict[str, ToolResult] | None = None,
) -> DimensionScore:
    """Score elegance: nesting depth, function length, naming, complexity.

    When Radon is available, P90 cyclomatic complexity adds a sub-score
    that captures branching density — a dimension of inelegance that
    nesting depth alone misses.
    """
    tool_results = tool_results or {}
    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]

    nestings = [f.max_nesting for f in source_files]
    if nestings:
        p90_idx = int(len(nestings) * 0.9)
        p90_nesting = sorted(nestings)[min(p90_idx, len(nestings) - 1)]
        nesting_score = sigmoid(p90_nesting, midpoint=4, k=1.5)
    else:
        p90_nesting = 0
        nesting_score = 100.0

    all_lengths = []
    for f in source_files:
        all_lengths.extend(f.function_lengths)
    if all_lengths:
        sorted_lengths = sorted(all_lengths)
        p90_idx = int(len(sorted_lengths) * 0.9)
        p90_length = sorted_lengths[min(p90_idx, len(sorted_lengths) - 1)]
        length_score = inverse_linear(p90_length, good=30, bad=100)
    else:
        p90_length = 0
        length_score = 100.0

    total_defs = sum(f.functions + f.classes for f in source_files)
    total_violations = sum(f.naming_violations for f in source_files)
    if total_defs > 0:
        naming_score = (1.0 - total_violations / total_defs) * 100.0
    else:
        naming_score = 100.0

    sub_scores: dict[str, float] = {
        "nesting_depth_p90": nesting_score,
        "function_length_p90": length_score,
        "naming_conventions": naming_score,
    }
    recommendations: list[str] = []

    radon = tool_results.get("radon")
    if radon and radon.success:
        p90_cc = radon.metrics.get("p90_complexity", 5)
        cc_score = sigmoid(p90_cc, midpoint=10, k=0.4)
        sub_scores["radon_complexity_p90"] = cc_score

        score = (
            nesting_score * 0.25
            + length_score * 0.25
            + naming_score * 0.25
            + cc_score * 0.25
        )

        if p90_cc > 15:
            recommendations.append(f"P90 cyclomatic complexity is {p90_cc} — simplify complex functions")
    else:
        score = (
            nesting_score * 0.35
            + length_score * 0.35
            + naming_score * 0.30
        )

    if p90_nesting > 4:
        recommendations.append(f"P90 nesting depth is {p90_nesting} — extract nested logic into helper functions")
    if p90_length > 50:
        recommendations.append(f"P90 function length is {p90_length} lines — break into smaller functions")
    if total_violations > 0:
        recommendations.append(f"{total_violations} naming convention violation(s) — use PEP 8 conventions")

    return DimensionScore(
        name="Elegance",
        score=score,
        sub_scores=sub_scores,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# 7. Reusability (weight: 0.10)
# ---------------------------------------------------------------------------


def score_reusability(
    project: ProjectAnalysis,
    code_map: dict | None = None,
) -> DimensionScore:
    """Score reusability: coupling, API surface ratio."""
    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]

    total_public = sum(f.public_definitions for f in source_files)
    total_private = sum(f.private_definitions for f in source_files)
    total_defs = total_public + total_private
    if total_defs > 0:
        api_ratio = total_public / total_defs
        if 0.3 <= api_ratio <= 0.6:
            api_score = 100.0
        elif api_ratio < 0.3:
            api_score = api_ratio / 0.3 * 100.0
        else:
            api_score = max(0.0, 100.0 - (api_ratio - 0.6) / 0.4 * 100.0)
    else:
        api_ratio = 0.0
        api_score = 50.0

    if code_map:
        graph = code_map.get("import_graph", {})
        ce_values = [len(deps) for deps in graph.values()]
        if ce_values:
            avg_ce = statistics.mean(ce_values)
            coupling_score = sigmoid(avg_ce, midpoint=8, k=0.4)
        else:
            coupling_score = 100.0
    else:
        coupling_score = 50.0

    if source_files:
        avg_lines = statistics.mean(f.lines for f in source_files)
        size_score = sigmoid(avg_lines, midpoint=200, k=0.02)
    else:
        size_score = 50.0

    score = (
        api_score * 0.35
        + coupling_score * 0.35
        + size_score * 0.30
    )

    recommendations = []
    if api_ratio > 0.7:
        recommendations.append(f"API surface is {api_ratio:.0%} public — consider making more internals private")
    if api_ratio < 0.2:
        recommendations.append(f"API surface is {api_ratio:.0%} public — very little is reusable")

    return DimensionScore(
        name="Reusability",
        score=score,
        sub_scores={
            "api_surface_ratio": api_score,
            "coupling": coupling_score,
            "module_size": size_score,
        },
        recommendations=recommendations,
    )
