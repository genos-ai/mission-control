"""Gate Request — durable record of an API-mode gate pause.

The `api` gate mode persists a row per gate point (pre_dispatch, pre_layer,
post_task, verification_failed, post_layer, post_run) and blocks on an
asyncio.Event keyed by request_id. An HTTP POST writes the decision back
and fires the Event, unblocking the dispatcher.

Mirrors the human_input_request pattern (Plan 45) but cross-cutting:
gates fire at every dispatch boundary, not just workflow-defined
human-input steps. See Plan 80g.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from modules.backend.models.base import Base, UUIDMixin


class GateRequestStatus(str, enum.Enum):
    PENDING = "pending"
    DECIDED = "decided"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class GateRequest(UUIDMixin, Base):
    """A durable API-mode gate pause record.

    Lifecycle: created PENDING by ConfigurableGate.review() → updated to
    DECIDED via POST /gates/{id}/decide → or TIMED_OUT if the dispatcher's
    wait expires → or CANCELLED if the mission is aborted while pending.
    """

    __tablename__ = "gate_requests"

    mission_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("mission_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Transport session the gate fired within (P15). Nullable for "
            "back-compat with rows where the dispatcher hadn't been wired."
        ),
    )
    gate_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="pre_dispatch | pre_layer | post_task | verification_failed | post_layer | post_run",
    )
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Serialised GateContext at the time of the pause.",
    )
    status: Mapped[str] = mapped_column(
        Enum(GateRequestStatus, native_enum=False),
        default=GateRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    decision_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialised GateDecision once a client POSTs a verdict.",
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    timed_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<GateRequest(id={self.id}, mission={self.mission_id[:8]}, "
            f"gate_type={self.gate_type}, status={self.status})>"
        )
