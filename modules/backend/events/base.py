"""SessionEvent, the base of every session lifecycle event (Plan 88, contract 3.6.1).

Lives apart from events/types.py so event modules such as
events/mission_run_types.py can subclass it without importing the registry.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from modules.backend.core.utils import utc_now


class SessionEvent(BaseModel):
    """Base class for all session lifecycle events."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    session_id: uuid.UUID
    timestamp: datetime = Field(default_factory=utc_now)
    source: str
    correlation_id: str | None = None
    trace_id: str | None = None
    metadata: dict = Field(default_factory=dict)
