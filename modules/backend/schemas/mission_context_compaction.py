"""MCD compaction result (Plan 88, 88.3.3)."""

from typing import Any

from pydantic import BaseModel, Field


class CompactionResult(BaseModel):
    """Outcome of one deterministic MCD compaction pass.

    from_bytes and to_bytes are mcd_size_bytes of the document before and after
    compaction. Each change is {change_type, path, old_value, new_value, reason},
    in the order it was applied.
    """

    from_bytes: int
    to_bytes: int
    changes: list[dict[str, Any]] = Field(default_factory=list)
    archived_paths: list[str] = Field(default_factory=list)
    reached_target: bool
