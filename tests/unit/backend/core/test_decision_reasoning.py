"""Tests for the stored format of a post-run supervisor decision's reasoning."""

import json

from modules.backend.core.decision_reasoning import (
    decode_decision_reasoning,
    encode_decision_reasoning,
)

META = {"action": "escalate", "reviewer": "config:rule_engine", "rule": 3, "model_metadata": None}


def test_round_trip_keeps_human_text_and_metadata():
    stored = encode_decision_reasoning("Stall detected: 3 waves with no progress.", META)

    decoded = decode_decision_reasoning(stored)

    assert decoded.human == "Stall detected: 3 waves with no progress."
    assert decoded.meta == META


def test_human_text_never_contains_the_tail():
    decoded = decode_decision_reasoning(encode_decision_reasoning("Out of budget.", META))

    assert "__META__" not in decoded.human
    assert "{" not in decoded.human


def test_multiline_human_text_survives():
    stored = encode_decision_reasoning("First line.\nSecond line.", META)

    assert decode_decision_reasoning(stored).human == "First line.\nSecond line."


def test_marker_inside_the_human_text_does_not_corrupt_the_decode():
    # The reason can be model output, so it may quote the marker.
    stored = encode_decision_reasoning("The log shows __META__ in its output.", META)

    decoded = decode_decision_reasoning(stored)

    assert decoded.human == "The log shows __META__ in its output."
    assert decoded.meta == META


def test_legacy_row_with_a_bare_json_last_line_is_decoded():
    # Written by the Haiku branch before the marker was unified.
    meta = {"action": "propose_complete", "reviewer": "ai:copilot:claude-haiku-4.5", "rule": 8}
    stored = f"The plan covers the brief.\n{json.dumps(meta)}"

    decoded = decode_decision_reasoning(stored)

    assert decoded.human == "The plan covers the brief."
    assert decoded.meta == meta


def test_reasoning_without_metadata_is_all_human_text():
    decoded = decode_decision_reasoning("  Just a reason.  ")

    assert decoded.human == "Just a reason."
    assert decoded.meta == {}


def test_last_line_json_without_an_action_is_not_treated_as_metadata():
    stored = 'Quoted payload:\n{"unrelated": 1}'

    decoded = decode_decision_reasoning(stored)

    assert decoded.human == stored
    assert decoded.meta == {}


def test_unparseable_tail_keeps_the_human_text_and_returns_no_metadata():
    decoded = decode_decision_reasoning("Some reason\n__META__{invalid json!!!}")

    assert decoded.human == "Some reason"
    assert decoded.meta == {}


def test_tail_that_is_not_an_object_returns_no_metadata():
    decoded = decode_decision_reasoning("Some reason\n__META__[1, 2]")

    assert decoded.human == "Some reason"
    assert decoded.meta == {}
