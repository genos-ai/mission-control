"""backfill workflow edge ids

The YAML-import path previously bypassed strict WorkflowEdgeSchema
validation because WorkflowSchema.edges was typed as list[dict].
Templates whose YAML omitted the edge `id` field were persisted as-is,
which silently broke the visual editor — React Flow collapses edges
that share a synthesized key (notably the multiple edges leaving
decision nodes like research-gate, stop-r1, stop-r2).

This migration backfills `id` on any persisted edge that is missing
one, using the same convention as WorkflowEdgeSchema._fill_id and
WorkflowDefinitionService._derive_edges:
    - source_handle in (None, '', 'output')  -> "{source}->{target}"
    - otherwise                              -> "{source}:{handle}->{target}"

Downgrade is a no-op: synthesized IDs are non-destructive.

Revision ID: plan81_001
Revises: plan80h_001
Create Date: 2026-05-26
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "plan81_001"
down_revision: Union[str, None] = "plan80h_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, edges_json FROM workflow_definitions")
    ).fetchall()

    for row in rows:
        edges = row.edges_json or []
        if not isinstance(edges, list):
            continue
        changed = False
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            if not edge.get("id"):
                source = edge.get("source", "")
                target = edge.get("target", "")
                handle = edge.get("source_handle") or "output"
                edge["id"] = (
                    f"{source}:{handle}->{target}"
                    if handle != "output"
                    else f"{source}->{target}"
                )
                changed = True
        if changed:
            conn.execute(
                sa.text(
                    "UPDATE workflow_definitions "
                    "SET edges_json = :edges WHERE id = :id"
                ),
                {"edges": json.dumps(edges), "id": row.id},
            )


def downgrade() -> None:
    # Synthesized IDs are not destructive; leaving them is safe.
    pass
