"""
Stored format of a post-run supervisor decision's reasoning.

``execution_decisions.reasoning`` is a single text column, but a supervisor
decision has two parts: a human-readable reason and structured metadata
(action, reviewer, rule, model metadata). They are stored together as

    <human reason>\\n__META__<json object>

This module is the only place that knows that format. Everything that
hands a reason to a person (events, notifications, Director prompts, chat,
logs) must use the decoded human text, never the stored column.
"""

import json
from typing import Any, NamedTuple

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

META_MARKER = "__META__"


class DecodedReasoning(NamedTuple):
    """A stored reasoning split into its two parts."""

    human: str
    meta: dict[str, Any]


def encode_decision_reasoning(human: str, meta: dict[str, Any]) -> str:
    """Join a human reason and its metadata into the stored column format."""
    return f"{human}\n{META_MARKER}{json.dumps(meta)}"


def decode_decision_reasoning(reasoning: str) -> DecodedReasoning:
    """Split a stored reasoning into human text and metadata.

    Rows written by the Haiku branch before the marker was unified carry a
    bare JSON object on their last line instead of the marker; they are read
    here so existing rows stay readable. Nothing writes that form any more.
    Metadata that cannot be parsed comes back empty, so the caller decides what
    an unknown decision means.
    """
    # The tail is written last and holds no free text, while the human reason can
    # (it may be model output), so split on the last marker.
    human, marker, raw_meta = reasoning.rpartition(META_MARKER)
    if marker:
        return DecodedReasoning(human.strip(), _parse_meta(raw_meta))

    head, _, last_line = reasoning.strip().rpartition("\n")
    legacy_meta = _parse_meta(last_line, quiet=True)
    if "action" in legacy_meta:
        return DecodedReasoning(head.strip(), legacy_meta)
    return DecodedReasoning(reasoning.strip(), {})


def _parse_meta(raw: str, *, quiet: bool = False) -> dict[str, Any]:
    try:
        meta = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        meta = None
    if isinstance(meta, dict):
        return meta
    if not quiet:
        logger.warning(
            "Could not parse the metadata tail of a decision reasoning",
            extra={"tail_preview": raw[:80]},
        )
    return {}
