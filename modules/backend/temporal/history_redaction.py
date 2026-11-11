"""Redaction of recorded Temporal histories (Plan 88 step 88.2.9).

Pure, no I/O. Histories committed under ``tests/fixtures/temporal_histories``
must carry no mission text: objectives, prompts, task output and failure text
(decision 15) are replaced while the JSON shape and value types are kept, so
the workflow's dataclasses still decode and the history still replays.
"""

import base64
import json
from typing import Any

REDACT_KEYS = frozenset(
    {
        "objective",
        "prompt",
        "output_data",
        "mission_brief",
        "message",
        "instructions",
        "failure_reason",
        "summary",
        # Free text the plan's list misses: run end detail carries activity
        # failure text, and reason carries the supervisor's LLM rationale.
        "detail",
        "reason",
    }
)
REDACTED = "<redacted>"
JSON_PLAIN = "json/plain"
# A Temporal Failure (ActivityTaskFailed, WorkflowExecutionFailed, timeouts and
# their nested ``cause`` chains) carries raw exception text outside any payload.
FAILURE_MARKERS = frozenset(
    {
        "stackTrace",
        "cause",
        "source",
        "applicationFailureInfo",
        "activityFailureInfo",
        "timeoutFailureInfo",
        "canceledFailureInfo",
        "terminatedFailureInfo",
        "serverFailureInfo",
        "resetWorkflowFailureInfo",
        "childWorkflowExecutionFailureInfo",
    }
)
FAILURE_TEXT_KEYS = ("message", "stackTrace")


def redact_history(history: dict) -> dict:
    """Redact every ``json/plain`` payload and every Failure's message and
    stack trace in a history dict, in place; returns it."""
    _walk(history)
    return history


def redact_value(value: Any) -> Any:
    """Replace every ``REDACT_KEYS`` value at any depth, in place; returns ``value``."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in REDACT_KEYS:
                value[key] = _blank(item)
            else:
                redact_value(item)
    elif isinstance(value, list):
        for item in value:
            redact_value(item)
    return value


def _blank(value: Any) -> Any:
    if isinstance(value, str):
        return REDACTED
    if isinstance(value, dict):
        return {}
    if isinstance(value, list):
        return []
    return value  # numbers, booleans and null are kept


def _walk(node: Any) -> None:
    if isinstance(node, dict):
        if _is_payload(node):
            _redact_payload(node)
            return
        if _is_failure(node):
            _redact_failure(node)
        for item in node.values():
            _walk(item)
    elif isinstance(node, list):
        for item in node:
            _walk(item)


def _is_payload(node: dict) -> bool:
    metadata = node.get("metadata")
    return isinstance(metadata, dict) and "encoding" in metadata and "data" in node


def _is_failure(node: dict) -> bool:
    return "message" in node and not FAILURE_MARKERS.isdisjoint(node)


def _redact_failure(failure: dict) -> None:
    """Blank failure text; ``_walk`` then recurses into ``cause`` and details.
    Replay does not compare failure strings, so determinism is unaffected."""
    for key in FAILURE_TEXT_KEYS:
        if isinstance(failure.get(key), str):
            failure[key] = REDACTED


def _redact_payload(payload: dict) -> None:
    if _decode(payload["metadata"]["encoding"]) != JSON_PLAIN:
        return
    decoded = json.loads(base64.b64decode(payload["data"]))
    redacted = redact_value(decoded)
    payload["data"] = base64.b64encode(
        json.dumps(redacted, separators=(",", ":")).encode()
    ).decode()


def _decode(field: str) -> str:
    """History JSON carries metadata values base64-encoded (protobuf bytes)."""
    return base64.b64decode(field).decode()
