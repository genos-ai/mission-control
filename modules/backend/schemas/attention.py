"""
Attention API schemas.

What needs a person across the missions they can see: one list for the dashboard and a count
per mission for the sidebar.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

AttentionKind = Literal["task_approval", "gate", "human_input", "retry"]


class AttentionItem(BaseModel):
    """One thing that needs attention, with the wording and the link already built.

    A gate request and a human-input request are an item each: each is its own decision.
    Proposed and failed tasks are one item per mission, with `count` saying how many.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    mission_name: str
    kind: AttentionKind
    title: str
    detail: str
    count: int
    created_at: datetime
    href: str


class AttentionResponse(BaseModel):
    """The attention list, most urgent first, and the number of items per mission."""

    model_config = ConfigDict(extra="forbid")

    items: list[AttentionItem]
    pending_counts: dict[str, int]
