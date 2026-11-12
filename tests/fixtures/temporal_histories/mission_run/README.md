# MissionRunWorkflow replay histories

Recorded `MissionRunWorkflow` histories, replayed against the current workflow
code by `tests/unit/backend/temporal/test_replay_histories.py` (Plan 88 step
88.2.9). A code change that alters the command sequence of any history here
fails CI in the "Temporal replay" step with a `NondeterminismError`. No
Temporal server is needed to replay.

## Recording

Stubbed scenarios (the seven Phase 2 fixtures and `p88-run-memory`). Each test in the module drives
one scenario through the real workflow with the stub activities in
`tests/integration/backend/temporal/mission_run_stubs.py`:

```bash
pytest tests/integration/backend/temporal/test_record_mission_run_histories.py --record-histories -q
```

Pass `-k <test name>` to record one new fixture; a bare run rewrites every
stubbed fixture from current code, which defeats the old-branch replays.

Histories from a real server (later patch fixtures, incident captures). The
workflow must be closed; the script refuses a running one:

```bash
python scripts/record_workflow_history.py record --workflow-id WORKFLOW_ID [--run-id RUN_ID] --name SLUG
```

Both write `<name>.json` in this directory. Re-record a stubbed fixture only
when its scenario changes; a history recorded from older code is the point of
the test, so never re-record one to make a replay failure go away.

## Redaction

Both paths pass the history through
`modules/backend/temporal/history_redaction.py` before writing. In every
`json/plain` payload, the value of each key in `REDACT_KEYS` (objective,
prompt, output_data, mission_brief, message, instructions, failure_reason,
summary, detail, reason), at any depth, is replaced: a string becomes
`"<redacted>"`, a dict `{}`, a list `[]`; numbers, booleans and `null` are
kept. The JSON shape and value types are unchanged, so the dataclasses still
decode and the history still replays. Every Temporal Failure (a dict with
`message` plus `stackTrace`, `cause`, `source` or a `*FailureInfo` key, as on
ActivityTaskFailed, ActivityTaskTimedOut and WorkflowExecutionFailed events)
has its `message` and `stackTrace` replaced with `"<redacted>"`, through the
whole `cause` chain; replay does not compare failure text. Review a new fixture for mission text
under any other key before committing it.

## Patch ids (88.2.8 rule 5)

Each step that introduces `workflow.patched("<id>")`, in the same commit:

1. adds `<id>` to `PATCH_IDS` in `modules/backend/temporal/versioning.py`;
2. records one history that takes the new branch, at `<id>.json` in this directory;
3. adds `<id>` to `REQUIRED` in `tests/unit/backend/temporal/test_replay_histories.py`.

Histories for the old branch are kept.
