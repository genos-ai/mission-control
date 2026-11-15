"""Registry of Temporal ``workflow.patched`` ids (Plan 88 step 88.2.8).

This module is the only place patch ids are declared. Policy lives in
``docs/10-reference-architecture/29-opt-temporal-workflow-versioning.md``;
``tests/unit/backend/temporal/test_patch_ids.py`` enforces it:

- every ``workflow.patched(...)`` call in a ``temporal/*workflow*.py`` module
  passes a string literal registered here;
- every id matches ``PATCH_ID_PATTERN`` (``p{plan}-{kebab-slug}``) and is never
  reused or renamed;
- every id has a recorded replay history under
  ``tests/fixtures/temporal_histories/mission_run/<id>.json``;
- ``workflow.deprecate_patch`` is never called.
"""

import re

PATCH_ID_PATTERN = re.compile(r"^p\d{2,3}-[a-z0-9]+(-[a-z0-9]+)*$")

PATCH_IDS: frozenset[str] = frozenset(
    {
        "p88-run-memory",  # 88.3.8: run-end compaction and digest before finalise
        "p88-lifecycle-signals",  # 88.4.5: pause/resume signals; run-end and tick notifications
    }
)
