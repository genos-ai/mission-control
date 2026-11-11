"""Tests for history_redaction (Plan 88 step 88.2.9)."""

import base64
import json

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from modules.backend.temporal.history_redaction import redact_history
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from tests.unit.backend.temporal.test_replay_histories import HISTORY_DIR


def _payload(value: object, encoding: str = "json/plain") -> dict:
    return {
        "metadata": {"encoding": base64.b64encode(encoding.encode()).decode()},
        "data": base64.b64encode(json.dumps(value).encode()).decode(),
    }


def _decoded(payload: dict) -> object:
    return json.loads(base64.b64decode(payload["data"]))


async def test_redacted_history_decodes():
    path = HISTORY_DIR / "two_layer_success.json"
    redacted = redact_history(json.loads(path.read_text()))
    history = WorkflowHistory.from_json(path.stem, json.dumps(redacted))
    await Replayer(workflows=[MissionRunWorkflow]).replay_workflow(history)


def test_redaction_keeps_types():
    history = {
        "input": {
            "payloads": [_payload({"objective": "x", "output_data": {"a": 1}, "cost_usd": 1.5})]
        }
    }

    redact_history(history)

    assert _decoded(history["input"]["payloads"][0]) == {
        "objective": "<redacted>",
        "output_data": {},
        "cost_usd": 1.5,
    }


def test_redaction_reaches_nested_keys_and_keeps_null():
    value = {
        "state": {"pending_gate": None, "items": [{"failure_reason": "boom", "prompt": ["p"]}]}
    }
    history = {"events": [{"result": {"payloads": [_payload(value)]}}]}

    redact_history(history)

    assert _decoded(history["events"][0]["result"]["payloads"][0]) == {
        "state": {"pending_gate": None, "items": [{"failure_reason": "<redacted>", "prompt": []}]}
    }


def test_redaction_covers_free_text_detail_and_reason():
    history = {"payloads": [_payload({"detail": "db password=hunter2", "reason": None})]}

    redact_history(history)

    assert _decoded(history["payloads"][0]) == {"detail": "<redacted>", "reason": None}


def test_non_json_payload_untouched():
    payload = _payload({"objective": "x"}, encoding="binary/plain")
    history = {"payloads": [dict(payload)]}

    redact_history(history)

    assert history["payloads"][0] == payload


def test_failure_text_redacted_through_cause_chain():
    history = {
        "events": [
            {
                "eventType": "EVENT_TYPE_ACTIVITY_TASK_FAILED",
                "activityTaskFailedEventAttributes": {
                    "failure": {
                        "message": "activity failed: token=abc",
                        "stackTrace": "Traceback ... secret",
                        "source": "PythonSDK",
                        "cause": {
                            "message": "ValueError: mission text",
                            "stackTrace": "Traceback ... nested",
                            "applicationFailureInfo": {
                                "type": "ValueError",
                                "nonRetryable": False,
                                "details": {"payloads": [_payload({"detail": "x", "n": 1})]},
                            },
                        },
                        "activityFailureInfo": {"activityType": {"name": "run_task"}},
                    },
                    "retryState": "RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED",
                },
            }
        ]
    }

    redact_history(history)

    failure = history["events"][0]["activityTaskFailedEventAttributes"]["failure"]
    assert failure["message"] == "<redacted>"
    assert failure["stackTrace"] == "<redacted>"
    assert failure["source"] == "PythonSDK"
    assert failure["activityFailureInfo"] == {"activityType": {"name": "run_task"}}
    cause = failure["cause"]
    assert cause["message"] == "<redacted>"
    assert cause["stackTrace"] == "<redacted>"
    assert cause["applicationFailureInfo"]["type"] == "ValueError"
    details = cause["applicationFailureInfo"]["details"]["payloads"][0]
    assert _decoded(details) == {"detail": "<redacted>", "n": 1}


def test_plain_dict_with_message_but_no_failure_marker_untouched():
    history = {"events": [{"message": "keep", "eventId": "1"}]}

    redact_history(history)

    assert history["events"][0]["message"] == "keep"
