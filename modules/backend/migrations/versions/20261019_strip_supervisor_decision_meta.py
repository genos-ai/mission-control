"""strip the stored metadata tail from persisted supervisor decision events

``mission_plan.supervisor_decision`` events were emitted with the stored
reasoning in ``data.reason``: the human reason followed by a metadata tail
(``\\n__META__{json}``; the Haiku branch wrote a bare ``\\n{"action": ...}``
line instead). The plan banner, the console and the narrative render
``data.reason`` as is, so the raw JSON showed. New events carry the human reason
only (see core/decision_reasoning.py); this rewrites the events already stored.

It cuts at the last tail, so a truncated one (the event reason was cut to 500
characters) is removed too. Rows with neither form are left alone, and a second
run changes nothing unless a reason itself contains a line shaped like a tail.

Downgrade is a no-op: the removed tail is a copy of what
``execution_decisions.reasoning`` still holds for the same decision.

Revision ID: strip_supervisor_decision_meta
Revises: plan81_002
Create Date: 2026-10-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "strip_supervisor_decision_meta"
down_revision: Union[str, None] = "plan81_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `data` is a json column, so it is cast to jsonb to set one key and back.
# The tail is matched as the writers produced it: a newline, then the marker and
# a JSON object. A bare marker inside the human text is not a tail, which also
# keeps a second run from touching rows the first one cleaned. In a Postgres
# regex `.` also matches a newline, so `^(.*)` keeps everything before the last
# tail.
STRIP_SQL = r"""
UPDATE mission_events
SET data = jsonb_set(
    data::jsonb,
    '{reason}',
    to_jsonb(
        btrim(
            CASE
                WHEN data->>'reason' ~ E'\n__META__\\{'
                    THEN regexp_replace(data->>'reason', E'^(.*)\n__META__\\{.*$', '\1')
                ELSE regexp_replace(data->>'reason', E'\n\\{"action":.*$', '')
            END,
            E' \n\t\r'
        )
    )
)::json
WHERE event_type = 'mission_plan.supervisor_decision'
  AND (
      data->>'reason' ~ E'\n__META__\\{'
      OR data->>'reason' ~ E'\n\\{"action":'
  )
"""


def upgrade() -> None:
    op.execute(STRIP_SQL)


def downgrade() -> None:
    # No-op: nothing to restore; the stripped text is still in execution_decisions.
    pass
