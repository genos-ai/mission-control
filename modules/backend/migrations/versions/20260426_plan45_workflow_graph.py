"""Add edges_json and canvas_state to workflow_definitions (Plan 45).

Stores React Flow edge data and viewport/node positions for the visual
workflow editor. Edges are derived from steps[].depends_on during the
data migration — the execution engine continues reading only depends_on.

Revision ID: plan45_workflow_graph
Revises: drop_notes_table
Create Date: 2026-04-26
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "plan45_workflow_graph"
down_revision: Union[str, None] = "drop_notes_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _derive_edges(steps: list[dict]) -> list[dict]:
    """Derive React Flow edges from steps[].depends_on."""
    edges = []
    for step in steps:
        step_id = step.get("id", "")
        for dep_id in step.get("depends_on", []):
            edges.append(
                {
                    "id": f"{dep_id}->{step_id}",
                    "source": dep_id,
                    "target": step_id,
                    "source_handle": "output",
                    "target_handle": "input",
                }
            )
    return edges


def upgrade() -> None:
    op.add_column(
        "workflow_definitions",
        sa.Column("edges_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "workflow_definitions",
        sa.Column("canvas_state", sa.JSON(), nullable=False, server_default="{}"),
    )

    # Backfill edges from existing steps[].depends_on
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, steps FROM workflow_definitions")).fetchall()

    for row in rows:
        row_id = row[0]
        steps_raw = row[1]
        steps = json.loads(steps_raw) if isinstance(steps_raw, str) else (steps_raw or [])
        edges = _derive_edges(steps)
        conn.execute(
            sa.text("UPDATE workflow_definitions SET edges_json = :edges WHERE id = :id"),
            {"edges": json.dumps(edges), "id": row_id},
        )


def downgrade() -> None:
    op.drop_column("workflow_definitions", "canvas_state")
    op.drop_column("workflow_definitions", "edges_json")
