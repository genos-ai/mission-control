"""PQI analysis dimensions — maintainability, security, modularity, testability.

These dimensions assess structural and analytical code quality.
"""

from __future__ import annotations

import statistics

from modules.backend.services.pqi.ast_analysis import ProjectAnalysis
from modules.backend.services.pqi.normalizers import (
    exp_decay,
    inverse_linear,
    ratio_score,
    sigmoid,
)
from modules.backend.services.pqi.tools import ToolResult
from modules.backend.services.pqi.types import DimensionScore


# ---------------------------------------------------------------------------
# Helpers (used by modularity)
# ---------------------------------------------------------------------------


def _count_cycles(graph: dict[str, list[str]]) -> int:
    """Count circular dependencies using DFS cycle detection."""
    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycles = 0

    def dfs(node: str) -> None:
        nonlocal cycles
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                cycles += 1
        rec_stack.discard(node)

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles


def _gini_coefficient(values: list[int | float]) -> float:
    """Compute Gini coefficient for a list of values (0=equal, 1=unequal)."""
    if not values or len(values) < 2:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_vals))
    return cumulative / (n * total)


# ---------------------------------------------------------------------------
# 1. Maintainability (weight: 0.20)
# ---------------------------------------------------------------------------


def score_maintainability(
    project: ProjectAnalysis,
    tool_results: dict[str, ToolResult] | None = None,
) -> DimensionScore:
    """Score maintainability: documentation, size, complexity, dead code signals.

    When Radon is available, its maintainability index (MI) replaces the
    cohesion heuristic — MI is a well-validated composite of Halstead
    volume, cyclomatic complexity, and lines of code.
    """
    tool_results = tool_results or {}
    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]

    # Sub-metric: documentation coverage
    total_callables = sum(f.total_callables for f in source_files)
    documented = sum(f.documented_callables for f in source_files)
    doc_coverage = ratio_score(documented, total_callables)

    # Sub-metric: file size distribution (P90 ≤ 300 lines → good)
    if source_files:
        sizes = sorted(f.lines for f in source_files)
        p90_idx = int(len(sizes) * 0.9)
        p90_size = sizes[min(p90_idx, len(sizes) - 1)]
        file_size_score = inverse_linear(p90_size, good=200, bad=800)
    else:
        p90_size = 0
        file_size_score = 100.0

    # Sub-metric: function length (P90 ≤ 30 lines → 100)
    all_lengths = []
    for f in source_files:
        all_lengths.extend(f.function_lengths)
    if all_lengths:
        sorted_lengths = sorted(all_lengths)
        p90_idx = int(len(sorted_lengths) * 0.9)
        p90_length = sorted_lengths[min(p90_idx, len(sorted_lengths) - 1)]
        func_length_score = inverse_linear(p90_length, good=30, bad=100)
    else:
        p90_length = 0
        func_length_score = 100.0

    sub_scores: dict[str, float] = {
        "doc_coverage": doc_coverage,
        "file_size_p90": file_size_score,
        "function_length_p90": func_length_score,
    }
    recommendations: list[str] = []

    # Radon MI replaces cohesion heuristic when available
    radon = tool_results.get("radon")
    if radon and radon.success:
        avg_mi = radon.metrics.get("avg_mi", 50.0)
        mi_score = min(100.0, max(0.0, avg_mi))
        sub_scores["radon_mi"] = mi_score

        score = (
            doc_coverage * 0.25
            + file_size_score * 0.20
            + func_length_score * 0.25
            + mi_score * 0.30
        )

        if avg_mi < 40:
            recommendations.append(f"Average maintainability index is {avg_mi:.0f} — refactor complex modules")
    else:
        if source_files:
            avg_funcs = statistics.mean(f.functions for f in source_files)
            cohesion_score = sigmoid(avg_funcs, midpoint=15, k=0.2)
        else:
            cohesion_score = 100.0
        sub_scores["cohesion"] = cohesion_score

        score = (
            doc_coverage * 0.30
            + file_size_score * 0.25
            + func_length_score * 0.25
            + cohesion_score * 0.20
        )

    if doc_coverage < 50:
        recommendations.append(f"Documentation coverage is {doc_coverage:.0f}% — add docstrings to public functions and classes")
    if p90_size > 500:
        recommendations.append(f"P90 file size is {p90_size} lines — split large files")
    if p90_length > 50:
        recommendations.append(f"P90 function length is {p90_length} lines — extract helper functions")

    return DimensionScore(
        name="Maintainability",
        score=score,
        sub_scores=sub_scores,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# 2. Security (weight: 0.15)
# ---------------------------------------------------------------------------


def score_security(
    project: ProjectAnalysis,
    tool_results: dict[str, ToolResult] | None = None,
) -> DimensionScore:
    """Score security: unsafe patterns, dangerous function calls, Bandit findings.

    When Bandit is available, its severity-weighted findings dominate
    the score (higher confidence, deeper analysis). AST-based detection
    fills in as a baseline when Bandit is unavailable.
    """
    tool_results = tool_results or {}
    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]
    kloc = max(project.source_lines / 1000, 0.1)

    total_unsafe = sum(len(f.unsafe_calls) for f in source_files)
    unsafe_per_kloc = total_unsafe / kloc
    ast_unsafe_score = exp_decay(unsafe_per_kloc, rate=1.0)

    files_with_unsafe = sum(1 for f in source_files if f.unsafe_calls)
    ast_clean_ratio = ratio_score(len(source_files) - files_with_unsafe, len(source_files)) if source_files else 100.0

    sub_scores: dict[str, float] = {
        "ast_unsafe_patterns": ast_unsafe_score,
        "ast_clean_file_ratio": ast_clean_ratio,
    }
    recommendations: list[str] = []
    confidence = 0.5

    bandit = tool_results.get("bandit")
    if bandit and bandit.success:
        confidence = 0.9

        metrics = bandit.metrics
        weighted_per_kloc = metrics.get("weighted_per_kloc", 0)
        high_count = int(metrics.get("high_severity", 0))
        medium_count = int(metrics.get("medium_severity", 0))
        low_count = int(metrics.get("low_severity", 0))

        bandit_density_score = exp_decay(weighted_per_kloc, rate=0.3)
        bandit_high_score = exp_decay(high_count, rate=1.5)
        bandit_medium_score = exp_decay(medium_count, rate=0.5)

        sub_scores["bandit_severity_density"] = bandit_density_score
        sub_scores["bandit_high_severity"] = bandit_high_score
        sub_scores["bandit_medium_severity"] = bandit_medium_score

        score = (
            bandit_density_score * 0.30
            + bandit_high_score * 0.25
            + bandit_medium_score * 0.15
            + ast_unsafe_score * 0.15
            + ast_clean_ratio * 0.15
        )

        if high_count > 0:
            recommendations.append(f"{high_count} HIGH severity finding(s) — fix immediately")
        if medium_count > 0:
            recommendations.append(f"{medium_count} MEDIUM severity finding(s) — review and remediate")
        if low_count > 0:
            recommendations.append(f"{low_count} LOW severity finding(s)")

        for finding in bandit.findings[:5]:
            if finding.severity in ("HIGH", "MEDIUM"):
                short_path = finding.file.split("/modules/")[-1] if "/modules/" in finding.file else finding.file
                recommendations.append(
                    f"[{finding.severity}] {short_path}:{finding.line} — "
                    f"{finding.message} ({finding.rule_id})"
                )
    else:
        score = ast_unsafe_score * 0.60 + ast_clean_ratio * 0.40

        if total_unsafe > 0:
            for f in source_files:
                for finding in f.unsafe_calls[:3]:
                    recommendations.append(f"{f.path}: {finding}")
            if total_unsafe > 3:
                recommendations.append(f"... and {total_unsafe - 3} more unsafe patterns")

        if bandit and not bandit.success:
            recommendations.append(f"Bandit error: {bandit.error}")
        elif not bandit:
            recommendations.append("Install bandit for deeper security analysis: pip install bandit")

    return DimensionScore(
        name="Security",
        score=score,
        sub_scores=sub_scores,
        confidence=confidence,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# 3. Modularity (weight: 0.15)
# ---------------------------------------------------------------------------


def score_modularity(
    project: ProjectAnalysis,
    code_map: dict | None = None,
) -> DimensionScore:
    """Score modularity: coupling, instability, circular deps, size distribution."""
    if not code_map:
        return DimensionScore(
            name="Modularity",
            score=50.0,
            confidence=0.3,
            recommendations=["Run with code map for accurate modularity scoring"],
        )

    graph = code_map.get("import_graph", {})

    ce = {m: len(deps) for m, deps in graph.items()}

    ca: dict[str, int] = {}
    for targets in graph.values():
        for t in targets:
            ca[t] = ca.get(t, 0) + 1

    all_modules = set(ce.keys()) | set(ca.keys())

    instabilities = []
    for m in all_modules:
        c_e = ce.get(m, 0)
        c_a = ca.get(m, 0)
        if c_e + c_a > 0:
            instabilities.append(c_e / (c_e + c_a))

    if instabilities:
        avg_instability = statistics.mean(instabilities)
        instability_score = 100.0 * (1.0 - abs(avg_instability - 0.5) * 2)
    else:
        instability_score = 50.0

    max_ce = max(ce.values()) if ce else 0
    coupling_score = sigmoid(max_ce, midpoint=15, k=0.3)

    cycle_count = _count_cycles(graph)
    cycle_score = exp_decay(cycle_count, rate=1.0)

    modules_data = code_map.get("modules", {})
    sizes = [m.get("lines", 0) for m in modules_data.values()]
    if len(sizes) > 1:
        gini = _gini_coefficient(sizes)
        gini_score = (1.0 - gini) * 100.0
    else:
        gini = 0.0
        gini_score = 100.0

    score = (
        instability_score * 0.25
        + coupling_score * 0.30
        + cycle_score * 0.25
        + gini_score * 0.20
    )

    recommendations = []
    if max_ce > 15:
        worst = max(ce, key=ce.get)
        recommendations.append(f"{worst} has Ce={max_ce} — too many dependencies, consider splitting")
    if cycle_count > 0:
        recommendations.append(f"{cycle_count} circular dependency(ies) detected — break with protocols or restructure")
    if gini > 0.6:
        recommendations.append(f"Module size Gini={gini:.2f} — sizes are very uneven, split large modules")

    return DimensionScore(
        name="Modularity",
        score=score,
        sub_scores={
            "instability_balance": instability_score,
            "coupling_max_ce": coupling_score,
            "circular_deps": cycle_score,
            "size_gini": gini_score,
        },
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# 4. Testability (weight: 0.15)
# ---------------------------------------------------------------------------


def score_testability(
    project: ProjectAnalysis,
    tool_results: dict[str, ToolResult] | None = None,
) -> DimensionScore:
    """Score testability: test-to-code ratio, complexity, function purity signals.

    When Radon is available, cyclomatic complexity replaces function length
    as the complexity proxy — cc directly measures decision paths, which
    is what makes code hard to test.
    """
    tool_results = tool_results or {}

    if project.source_lines > 0:
        test_ratio = project.test_lines / project.source_lines
        ratio_score_val = sigmoid(abs(test_ratio - 1.0), midpoint=0.8, k=3.0)
    else:
        test_ratio = 0.0
        ratio_score_val = 0.0

    if project.source_files > 0:
        file_ratio = project.test_files / project.source_files
        file_ratio_score = min(100.0, file_ratio * 100.0)
    else:
        file_ratio = 0.0
        file_ratio_score = 0.0

    source_files = [f for f in project.files if "/tests/" not in f.path and not f.path.startswith("tests/")]

    max_nestings = [f.max_nesting for f in source_files if f.max_nesting > 0]
    if max_nestings:
        avg_nesting = statistics.mean(max_nestings)
        nesting_score = sigmoid(avg_nesting, midpoint=4, k=1.0)
    else:
        nesting_score = 100.0

    sub_scores: dict[str, float] = {
        "test_code_ratio": ratio_score_val,
        "test_file_ratio": file_ratio_score,
        "avg_nesting_depth": nesting_score,
    }
    recommendations: list[str] = []

    radon = tool_results.get("radon")
    if radon and radon.success:
        avg_cc = radon.metrics.get("avg_complexity", 5.0)
        complexity_score = sigmoid(avg_cc, midpoint=10, k=0.3)
        sub_scores["radon_avg_complexity"] = complexity_score

        simple_ratio = radon.metrics.get("simple_ratio", 1.0)
        simple_score = simple_ratio * 100.0
        sub_scores["simple_function_ratio"] = simple_score

        score = (
            ratio_score_val * 0.30
            + file_ratio_score * 0.15
            + complexity_score * 0.25
            + simple_score * 0.15
            + nesting_score * 0.15
        )

        if avg_cc > 10:
            recommendations.append(f"Average cyclomatic complexity is {avg_cc:.1f} — simplify branching logic")
        complex_count = sum(
            int(radon.metrics.get(f"rank_{r}", 0))
            for r in ("D", "E", "F")
        )
        if complex_count > 0:
            recommendations.append(f"{complex_count} function(s) with complexity rank D+ — refactor or split")
    else:
        all_lengths = []
        for f in source_files:
            all_lengths.extend(f.function_lengths)
        if all_lengths:
            avg_length = statistics.mean(all_lengths)
            length_score = sigmoid(avg_length, midpoint=25, k=0.15)
        else:
            length_score = 100.0
        sub_scores["avg_function_length"] = length_score

        score = (
            ratio_score_val * 0.35
            + file_ratio_score * 0.20
            + length_score * 0.25
            + nesting_score * 0.20
        )

    if test_ratio < 0.5:
        recommendations.append(f"Test-to-code ratio is {test_ratio:.2f} — aim for 0.8-1.2")
    if project.test_files == 0:
        recommendations.append("No test files found")

    return DimensionScore(
        name="Testability",
        score=score,
        sub_scores=sub_scores,
        recommendations=recommendations,
    )
