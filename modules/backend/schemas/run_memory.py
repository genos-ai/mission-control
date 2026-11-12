"""Run memory schemas (Plan 88, 88.3.5, 88.3.6).

The run context packet: what run N carries forward from run N-1, namely
the previous run's digest and the Mission Context Document (MCD) changes
between the two runs' start watermarks. Also the digest agent's output type,
kept here so services never import the agents layer.
"""

from pydantic import BaseModel


class PreviousRunDigest(BaseModel):
    """The previous run's digest, summary truncated to previous_digest_max_chars."""

    mission_run_id: str
    sequence: int
    status: str  # MissionRunStatus value
    generator: str  # DigestGenerator value
    summary: str
    open_items: list[dict]
    metrics: dict


class ContextDeltaEntry(BaseModel):
    """One MCD change, value and reason truncated to context_delta_value_max_chars."""

    version: int
    change_type: str  # ChangeType value
    path: str
    value_excerpt: str | None
    reason: str


class ContextDelta(BaseModel):
    """MCD changes with from_version < version <= to_version, oldest first."""

    from_version: int
    to_version: int
    entries: list[ContextDeltaEntry]
    omitted_count: int


class RunContextPacket(BaseModel):
    """Run-scoped context layers; both are None on a mission's first run."""

    mission_run_id: str
    is_first_run: bool
    previous_run_digest: PreviousRunDigest | None
    context_delta: ContextDelta | None


class DigestOpenItemOut(BaseModel):
    """One open item the digest agent reports, citing the task it came from."""

    text: str
    source_task_id: str | None


class DigestHeadlineOut(BaseModel):
    """A one-line headline for one task of the run."""

    task_id: str
    headline: str


class DigestNarrative(BaseModel):
    """The digest agent's output: the narrative half of a run digest."""

    summary: str
    open_items: list[DigestOpenItemOut]
    headlines: list[DigestHeadlineOut]
