"""
Safe condition expression evaluator for workflow condition nodes.

Tokenize → parse → evaluate against a context dict. No eval(), no
arbitrary code execution. Supports variable references (@node.step_id.field
and @context.key), comparison operators, compound logic (AND/OR/NOT),
and common unary checks (is_empty, is_not_empty).

Syntax examples:
    @node.check.score >= 0.7
    @context.mode == "approved"
    @node.scan.findings is_empty
    @node.check.score > 0.8 AND @context.mode == "strict"
    NOT @node.check.flagged
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TokenType(Enum):
    REF = auto()  # @node.step_id.field or @context.key
    STRING = auto()  # "quoted string"
    NUMBER = auto()  # 123, 45.6
    BOOL = auto()  # true, false
    NULL = auto()  # null
    OP = auto()  # ==, !=, >, >=, <, <=, contains, not_contains
    UNARY_OP = auto()  # is_empty, is_not_empty
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: Any


_KEYWORDS = {
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "true": TokenType.BOOL,
    "false": TokenType.BOOL,
    "null": TokenType.NULL,
    "contains": TokenType.OP,
    "not_contains": TokenType.OP,
    "is_empty": TokenType.UNARY_OP,
    "is_not_empty": TokenType.UNARY_OP,
}

_REF_RE = re.compile(r"@[a-zA-Z_][a-zA-Z0-9_.\-]*")
_NUM_RE = re.compile(r"-?\d+(\.\d+)?")
_STR_RE = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
_OP_RE = re.compile(r"(==|!=|>=|<=|>|<)")


def tokenize(expression: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    s = expression.strip()

    while i < len(s):
        if s[i].isspace():
            i += 1
            continue

        # Parentheses
        if s[i] == "(":
            tokens.append(Token(TokenType.LPAREN, "("))
            i += 1
            continue
        if s[i] == ")":
            tokens.append(Token(TokenType.RPAREN, ")"))
            i += 1
            continue

        # String literal
        m = _STR_RE.match(s, i)
        if m:
            tokens.append(Token(TokenType.STRING, m.group(1)))
            i = m.end()
            continue

        # Reference (@node.x.y or @context.key)
        m = _REF_RE.match(s, i)
        if m:
            tokens.append(Token(TokenType.REF, m.group()))
            i = m.end()
            continue

        # Comparison operators (must check before number to avoid - ambiguity)
        m = _OP_RE.match(s, i)
        if m:
            tokens.append(Token(TokenType.OP, m.group()))
            i = m.end()
            continue

        # Number
        m = _NUM_RE.match(s, i)
        if m:
            val = float(m.group()) if "." in m.group() else int(m.group())
            tokens.append(Token(TokenType.NUMBER, val))
            i = m.end()
            continue

        # Keywords (AND, OR, NOT, true, false, null, contains, etc.)
        word_m = re.match(r"[a-zA-Z_][a-zA-Z0-9_]*", s[i:])
        if word_m:
            word = word_m.group().lower()
            if word in _KEYWORDS:
                tt = _KEYWORDS[word]
                if tt == TokenType.BOOL:
                    tokens.append(Token(TokenType.BOOL, word == "true"))
                elif tt == TokenType.NULL:
                    tokens.append(Token(TokenType.NULL, None))
                else:
                    tokens.append(Token(tt, word))
                i += word_m.end()
                continue

        raise ConditionEvaluationError(f"Unexpected character at position {i}: '{s[i]}'")

    tokens.append(Token(TokenType.EOF, None))
    return tokens


# ---------------------------------------------------------------------------
# AST Nodes
# ---------------------------------------------------------------------------


@dataclass
class CompareExpr:
    left: Any  # resolved value or ref
    op: str
    right: Any


@dataclass
class UnaryCheckExpr:
    ref: str
    op: str  # is_empty, is_not_empty


@dataclass
class BoolBinExpr:
    left: Any
    op: str  # AND, OR
    right: Any


@dataclass
class NotExpr:
    child: Any


@dataclass
class LiteralExpr:
    value: Any


@dataclass
class RefExpr:
    path: str


# ---------------------------------------------------------------------------
# Parser — recursive descent
# ---------------------------------------------------------------------------


class ConditionEvaluationError(Exception):
    pass


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, tt: TokenType) -> Token:
        t = self.advance()
        if t.type != tt:
            raise ConditionEvaluationError(f"Expected {tt}, got {t.type}")
        return t

    def parse(self) -> Any:
        expr = self._or_expr()
        if self.peek().type != TokenType.EOF:
            raise ConditionEvaluationError(f"Unexpected token after expression: {self.peek()}")
        return expr

    def _or_expr(self) -> Any:
        left = self._and_expr()
        while self.peek().type == TokenType.OR:
            self.advance()
            right = self._and_expr()
            left = BoolBinExpr(left, "OR", right)
        return left

    def _and_expr(self) -> Any:
        left = self._not_expr()
        while self.peek().type == TokenType.AND:
            self.advance()
            right = self._not_expr()
            left = BoolBinExpr(left, "AND", right)
        return left

    def _not_expr(self) -> Any:
        if self.peek().type == TokenType.NOT:
            self.advance()
            child = self._not_expr()
            return NotExpr(child)
        return self._comparison()

    def _comparison(self) -> Any:
        left = self._primary()

        # Unary operator (is_empty, is_not_empty) — applies to a ref
        if self.peek().type == TokenType.UNARY_OP:
            op = self.advance().value
            return UnaryCheckExpr(ref=left, op=op)

        # Binary comparison
        if self.peek().type == TokenType.OP:
            op = self.advance().value
            right = self._primary()
            return CompareExpr(left, op, right)

        return left

    def _primary(self) -> Any:
        t = self.peek()

        if t.type == TokenType.LPAREN:
            self.advance()
            expr = self._or_expr()
            self.expect(TokenType.RPAREN)
            return expr
        if t.type == TokenType.REF:
            self.advance()
            return RefExpr(t.value)
        if t.type == TokenType.STRING:
            self.advance()
            return LiteralExpr(t.value)
        if t.type == TokenType.NUMBER:
            self.advance()
            return LiteralExpr(t.value)
        if t.type == TokenType.BOOL:
            self.advance()
            return LiteralExpr(t.value)
        if t.type == TokenType.NULL:
            self.advance()
            return LiteralExpr(None)

        raise ConditionEvaluationError(f"Unexpected token: {t}")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def resolve_ref(path: str, completed_outcomes: dict[str, dict], workflow_context: dict) -> Any:
    """Resolve @node.step_id.field or @context.key against runtime data.

    Public function. Used by workflow upstream-context resolution
    (services/workflow.py) and tool_call/llm_call template substitution.

    Raises ConditionEvaluationError on structural errors (unknown reference
    root). Returns None when the data path is missing (e.g. a skipped
    predecessor) — callers distinguish these by catching the exception.
    """
    parts = path.lstrip("@").split(".")

    if parts[0] == "node" and len(parts) >= 3:
        step_id = parts[1]
        field_path = parts[2:]
        data = completed_outcomes.get(step_id, {})
        # Walk nested output — first check under "output" key (executor contract).
        # If the data has an "output" key, auto-unwrap it. When the caller
        # also asks for ".output" in field_path (e.g. @node.X.output), skip
        # that segment since the auto-unwrap already consumed it.
        auto_unwrapped = "output" in data
        output = data.get("output", data)
        walk_path = field_path
        if auto_unwrapped and walk_path and walk_path[0] == "output":
            walk_path = walk_path[1:]
        for key in walk_path:
            if isinstance(output, dict):
                output = output.get(key)
            else:
                return None
        return output

    if parts[0] == "context" and len(parts) >= 2:
        key = ".".join(parts[1:])
        return workflow_context.get(key)

    raise ConditionEvaluationError(
        f"Unknown reference root: {parts[0]} (expected 'node' or 'context')"
    )


def _eval(node: Any, outcomes: dict[str, dict], ctx: dict) -> Any:
    if isinstance(node, LiteralExpr):
        return node.value

    if isinstance(node, RefExpr):
        return resolve_ref(node.path, outcomes, ctx)

    if isinstance(node, CompareExpr):
        left = _eval(node.left, outcomes, ctx)
        right = _eval(node.right, outcomes, ctx)
        return _compare(left, node.op, right)

    if isinstance(node, UnaryCheckExpr):
        val = _eval(node.ref, outcomes, ctx)
        if node.op == "is_empty":
            return _is_empty(val)
        if node.op == "is_not_empty":
            return not _is_empty(val)

    if isinstance(node, BoolBinExpr):
        left = _eval(node.left, outcomes, ctx)
        right = _eval(node.right, outcomes, ctx)
        if node.op == "AND":
            return bool(left) and bool(right)
        return bool(left) or bool(right)

    if isinstance(node, NotExpr):
        return not bool(_eval(node.child, outcomes, ctx))

    raise ConditionEvaluationError(f"Unknown AST node: {type(node)}")


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op in (">", ">=", "<", "<="):
        try:
            l, r = float(left), float(right)
        except (TypeError, ValueError):
            return False
        if op == ">":
            return l > r
        if op == ">=":
            return l >= r
        if op == "<":
            return l < r
        return l <= r
    if op == "contains":
        if isinstance(left, str):
            return str(right) in left
        if isinstance(left, (list, tuple)):
            return right in left
        return False
    if op == "not_contains":
        return not _compare(left, "contains", right)
    raise ConditionEvaluationError(f"Unknown operator: {op}")


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, (str, list, tuple, dict)):
        return len(val) == 0
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_condition(
    expression: str,
    completed_outcomes: dict[str, dict],
    workflow_context: dict | None = None,
) -> bool:
    """Evaluate a condition expression against runtime data.

    Returns True/False. Raises ConditionEvaluationError on parse/eval failure.
    """
    tokens = tokenize(expression)
    ast = _Parser(tokens).parse()
    result = _eval(ast, completed_outcomes, workflow_context or {})
    return bool(result)


def evaluate_expression(
    expression: str,
    completed_outcomes: dict[str, dict],
    workflow_context: dict | None = None,
) -> str:
    """Evaluate an expression and return its string result.

    Unlike evaluate_condition() which coerces to bool, this returns the
    raw expression result as a string. Used by decision node rule resolver.

    Raises ConditionEvaluationError on failure.
    """
    tokens = tokenize(expression)
    ast = _Parser(tokens).parse()
    result = _eval(ast, completed_outcomes, workflow_context or {})
    return str(result).strip()


_STANDALONE_TEMPLATE_RE = re.compile(r"^\s*\{\{(@[^}]+)\}\}\s*$")
_TEMPLATE_RE = re.compile(r"\{\{(@[^}]+)\}\}")


def resolve_template(
    template: Any,
    completed_outcomes: dict[str, dict],
    workflow_context: dict | None = None,
) -> Any:
    """Resolve {{@node.x.y}} and {{@context.k}} placeholders in a template.

    Plan 79 §8.5 — Fails loud on structural errors (typo in ref root, e.g.
    `@nodez.X`). The previous swallow-and-leave-marker behaviour violated
    the fail-fast project principle and masked YAML typos.

    Plan 79 §8.6 — Preserves Python type when the entire input is a
    single ref. `"{{@node.X.output}}"` resolving to a dict returns the
    dict, not `str(dict)`. Mixed text continues to produce a string.

    Args:
        template: Template string. Non-strings are returned unchanged
            (so this is safe to call inside a generic walker).
        completed_outcomes: Wave engine's completed-step outcomes map.
        workflow_context: Workflow context dict.

    Returns:
        The resolved value. Same Python type as the resolved ref when the
        template is a standalone ref; otherwise a string with the
        substitutions applied.

    Raises:
        ConditionEvaluationError: when a ref has a structural error
            (unknown root). Missing-data paths (skipped predecessor)
            continue to resolve to None / empty-string.
    """
    if not isinstance(template, str):
        return template
    ctx = workflow_context or {}

    # Standalone ref: preserve the resolved value's Python type.
    m = _STANDALONE_TEMPLATE_RE.match(template)
    if m:
        return resolve_ref(m.group(1).strip(), completed_outcomes, ctx)

    # Multi-ref or mixed-text: string substitution.
    def _replace(match: re.Match) -> str:
        # No try/except: structural errors propagate as ConditionEvaluationError
        # so YAML typos fail at the call site instead of leaving literal markers.
        val = resolve_ref(match.group(1).strip(), completed_outcomes, ctx)
        return str(val) if val is not None else ""

    return _TEMPLATE_RE.sub(_replace, template)


# =============================================================================
# walk_refs — generic recursive walker, parameterised by leaf resolver
# =============================================================================


def walk_refs(
    value: Any,
    completed_outcomes: dict[str, dict],
    workflow_context: dict | None = None,
    *,
    leaf_resolver,
) -> Any:
    """Recursively walk str/dict/list values, applying leaf_resolver to strings.

    Used by both agent_step input resolution (services/workflow.py) and
    tool_call args resolution (services/workflow_run_waves.py). The two
    call sites differ only in their leaf_resolver — agent_step uses
    bare-ref resolution; tool_call uses template substitution.

    Args:
        value: A value of any type. dict/list are walked recursively; str
            values are passed to leaf_resolver; other types pass through
            unchanged.
        completed_outcomes: Forwarded to leaf_resolver via closure (the
            leaf_resolver typically captures these already).
        workflow_context: Same.
        leaf_resolver: Callable[[str], Any] applied to every string leaf.
            Returns the resolved value (any type). May raise.

    Returns:
        A new structure with the same shape, leaves replaced.
    """
    if isinstance(value, str):
        return leaf_resolver(value)
    if isinstance(value, dict):
        return {
            k: walk_refs(v, completed_outcomes, workflow_context, leaf_resolver=leaf_resolver)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            walk_refs(v, completed_outcomes, workflow_context, leaf_resolver=leaf_resolver)
            for v in value
        ]
    return value
