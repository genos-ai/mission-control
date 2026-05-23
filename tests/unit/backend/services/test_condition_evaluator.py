"""
Tests for condition_evaluator's public surface.

Phase 1 (Plan 79) promotes _resolve_ref → resolve_ref and adds fail-loud
behaviour to resolve_template (§8.5) plus standalone-ref type preservation
(§8.6). This file tests the public API.
"""

from __future__ import annotations

import pytest

from modules.backend.services.condition_evaluator import (
    ConditionEvaluationError,
    evaluate_condition,
    resolve_ref,
    resolve_template,
    walk_refs,
)


# =============================================================================
# resolve_ref — public function (Plan 79 §8.0 promotion)
# =============================================================================


class TestResolveRefPublicAPI:
    """resolve_ref is the public ref-resolver. Used by upstream-context
    resolution and template substitution."""

    def test_imports_from_public_path(self):
        # Pure smoke: the function is importable under the public name.
        # If a future change accidentally re-privatises it, this fails.
        assert callable(resolve_ref)

    def test_resolves_node_ref_with_auto_output_unwrap(self):
        outcomes = {"step1": {"output": {"value": 42}}}
        assert resolve_ref("@node.step1.value", outcomes, {}) == 42

    def test_resolves_node_ref_with_explicit_output_segment(self):
        outcomes = {"step1": {"output": {"value": 42}}}
        # The .output segment is consumed by auto-unwrap; both forms work.
        assert resolve_ref("@node.step1.output.value", outcomes, {}) == 42

    def test_resolves_node_ref_without_output_wrapper(self):
        outcomes = {"step1": {"value": 42}}
        assert resolve_ref("@node.step1.value", outcomes, {}) == 42

    def test_resolves_context_ref(self):
        assert resolve_ref("@context.question", {}, {"question": "hello"}) == "hello"

    def test_returns_none_for_missing_step(self):
        # Legitimate missing-data path — skipped predecessor scenario.
        assert resolve_ref("@node.missing.output", {}, {}) is None

    def test_returns_none_for_missing_field(self):
        outcomes = {"step1": {"output": {"value": 42}}}
        assert resolve_ref("@node.step1.nonexistent", outcomes, {}) is None

    def test_returns_none_for_skipped_predecessor(self):
        # _execute_step writes {"_skipped": True} for skipped nodes.
        outcomes = {"step1": {"_skipped": True}}
        assert resolve_ref("@node.step1.output", outcomes, {}) is None

    def test_raises_on_unknown_ref_root(self):
        # Structural error — fail loud.
        with pytest.raises(ConditionEvaluationError):
            resolve_ref("@unknown.x.y", {}, {})

    def test_resolves_dict_field_to_dict_value(self):
        # Critical for sparse topology: @node.critic.output.attacks.systems
        # walks down to the inner dict.
        outcomes = {
            "critic": {
                "output": {
                    "attacks": {
                        "systems": {"assumption": "x", "attack": "y"},
                        "quant": {"assumption": "a", "attack": "b"},
                    },
                },
            },
        }
        result = resolve_ref("@node.critic.output.attacks.systems", outcomes, {})
        assert result == {"assumption": "x", "attack": "y"}


# =============================================================================
# evaluate_condition — sanity that the internal rename didn't break anything
# =============================================================================


class TestEvaluateConditionStillWorks:
    """Smoke check that evaluate_condition (which uses resolve_ref internally
    via _eval / RefExpr) still works after the rename."""

    def test_simple_equality_against_context(self):
        assert evaluate_condition('@context.x == "yes"', {}, {"x": "yes"}) is True
        assert evaluate_condition('@context.x == "yes"', {}, {"x": "no"}) is False

    def test_node_field_comparison(self):
        outcomes = {"check": {"output": {"score": 0.9}}}
        assert evaluate_condition("@node.check.score > 0.7", outcomes, {}) is True
        assert evaluate_condition("@node.check.score > 0.95", outcomes, {}) is False


# =============================================================================
# resolve_template — current behaviour smoke (before §8.5 / §8.6 changes)
# =============================================================================


class TestResolveTemplateSmoke:
    """Behaviour shared with the previous resolve_template — preserved
    after §8.5 / §8.6 changes."""

    def test_simple_substitution(self):
        outcomes = {"x": {"output": "hello"}}
        assert resolve_template("Greeting: {{@node.x.output}}", outcomes, {}) == "Greeting: hello"

    def test_context_substitution(self):
        assert resolve_template("Q: {{@context.q}}", {}, {"q": "why"}) == "Q: why"

    def test_no_template_passthrough(self):
        assert resolve_template("plain text", {}, {}) == "plain text"

    def test_skipped_predecessor_substitutes_empty(self):
        # Mixed-text template: skipped ref still substitutes empty (None → "").
        outcomes = {"skipped": {"_skipped": True}}
        assert resolve_template("Before {{@node.skipped.output}} after", outcomes, {}) == "Before  after"


# =============================================================================
# §8.5 — resolve_template fails loud on structural errors
# =============================================================================


class TestResolveTemplateFailLoud:
    """Plan 79 §8.5 — structural errors (typo in ref root) propagate
    instead of silently leaving the literal {{@badref}} marker."""

    def test_typo_in_ref_root_raises(self):
        # @nodez.X is a typo (should be @node.X) — fail loud.
        with pytest.raises(ConditionEvaluationError):
            resolve_template("Hello {{@nodez.x.y}}", {}, {})

    def test_typo_in_standalone_ref_raises(self):
        # Standalone-ref path also fails loud on structural error.
        with pytest.raises(ConditionEvaluationError):
            resolve_template("{{@badroot.x}}", {}, {})

    def test_skipped_predecessor_does_not_raise(self):
        # Missing-data path is NOT a structural error — silently substitutes "".
        outcomes = {"skipped": {"_skipped": True}}
        result = resolve_template("X: {{@node.skipped.output}}", outcomes, {})
        assert result == "X: "

    def test_missing_field_does_not_raise(self):
        # Missing field walk returns None → "".
        outcomes = {"step": {"output": {"a": 1}}}
        assert resolve_template("X: {{@node.step.missing}}", outcomes, {}) == "X: "


# =============================================================================
# §8.6 — standalone refs preserve Python type
# =============================================================================


class TestResolveTemplateStandaloneType:
    """Plan 79 §8.6 — when the entire template is a single ref, the
    resolved value's Python type is preserved. Mixed text → string."""

    def test_standalone_dict_preserved(self):
        # Critical for store_artifact JSON path and tool_args dict refs.
        outcomes = {"x": {"output": {"a": 1, "b": 2}}}
        result = resolve_template("{{@node.x.output}}", outcomes, {})
        assert result == {"a": 1, "b": 2}
        assert isinstance(result, dict)

    def test_standalone_list_preserved(self):
        outcomes = {"x": {"output": [1, 2, 3]}}
        result = resolve_template("{{@node.x.output}}", outcomes, {})
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_standalone_float_preserved(self):
        # Critical for store_learning.confidence which expects float.
        outcomes = {"x": {"output": {"confidence": 0.85}}}
        result = resolve_template("{{@node.x.output.confidence}}", outcomes, {})
        assert result == 0.85
        assert isinstance(result, float)

    def test_standalone_int_preserved(self):
        outcomes = {"x": {"output": {"count": 42}}}
        assert resolve_template("{{@node.x.output.count}}", outcomes, {}) == 42

    def test_standalone_bool_preserved(self):
        outcomes = {"x": {"output": {"passed": True}}}
        result = resolve_template("{{@node.x.output.passed}}", outcomes, {})
        assert result is True

    def test_standalone_string_still_string(self):
        outcomes = {"x": {"output": "hello"}}
        assert resolve_template("{{@node.x.output}}", outcomes, {}) == "hello"

    def test_standalone_none_when_skipped(self):
        # Standalone ref to a skipped predecessor returns None (raw value).
        outcomes = {"skipped": {"_skipped": True}}
        assert resolve_template("{{@node.skipped.output}}", outcomes, {}) is None

    def test_whitespace_around_standalone_tolerated(self):
        outcomes = {"x": {"output": 42}}
        assert resolve_template("  {{@node.x.output}}  ", outcomes, {}) == 42

    def test_mixed_text_produces_string_even_with_dict_ref(self):
        # When the template has surrounding text, str()-coercion kicks in.
        outcomes = {"x": {"output": {"a": 1}}}
        result = resolve_template("data: {{@node.x.output}}", outcomes, {})
        assert isinstance(result, str)
        assert result == "data: {'a': 1}"

    def test_non_string_input_returned_unchanged(self):
        # Safety: resolve_template inside a walker may receive non-strings.
        assert resolve_template(42, {}, {}) == 42
        assert resolve_template({"a": 1}, {}, {}) == {"a": 1}
        assert resolve_template(None, {}, {}) is None


# =============================================================================
# walk_refs — generic recursive walker (Plan 79 §8.1)
# =============================================================================


class TestWalkRefs:
    """Plan 79 §8.1 — generic recursive walker used by both agent_step
    input resolver and tool_call args resolver."""

    def test_walks_dict_recursively(self):
        outcomes = {"x": {"output": "X"}, "y": {"output": "Y"}}
        value = {"a": "{{@node.x.output}}", "nested": {"b": "{{@node.y.output}}"}}
        result = walk_refs(
            value, outcomes, {},
            leaf_resolver=lambda s: resolve_template(s, outcomes, {}),
        )
        assert result == {"a": "X", "nested": {"b": "Y"}}

    def test_walks_list_recursively(self):
        outcomes = {"x": {"output": 1}, "y": {"output": 2}}
        value = ["{{@node.x.output}}", "{{@node.y.output}}", "static"]
        result = walk_refs(
            value, outcomes, {},
            leaf_resolver=lambda s: resolve_template(s, outcomes, {}),
        )
        assert result == [1, 2, "static"]

    def test_preserves_nested_dict_structure(self):
        outcomes = {"a": {"output": {"v": 1}}, "b": {"output": {"v": 2}}}
        value = {
            "round_1": {
                "x": "{{@node.a.output}}",
                "y": "{{@node.b.output}}",
            },
        }
        result = walk_refs(
            value, outcomes, {},
            leaf_resolver=lambda s: resolve_template(s, outcomes, {}),
        )
        assert result == {"round_1": {"x": {"v": 1}, "y": {"v": 2}}}

    def test_non_string_leaves_passthrough(self):
        # Ints, floats, bools, None pass through.
        value = {"a": 42, "b": 3.14, "c": True, "d": None, "e": "static"}
        result = walk_refs(
            value, {}, {},
            leaf_resolver=lambda s: s.upper() if isinstance(s, str) else s,
        )
        assert result == {"a": 42, "b": 3.14, "c": True, "d": None, "e": "STATIC"}

    def test_works_with_bare_ref_resolver(self):
        # Agent_step input convention: bare refs (no braces).
        outcomes = {"x": {"output": "hello"}}
        value = {"q": "@node.x.output"}

        def _bare_leaf(s: str):
            return resolve_ref(s, outcomes, {}) if s.startswith("@") else s

        result = walk_refs(value, outcomes, {}, leaf_resolver=_bare_leaf)
        assert result == {"q": "hello"}
