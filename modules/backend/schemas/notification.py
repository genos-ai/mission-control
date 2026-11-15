"""Mission notification recipient schemas (Plan 88 step 88.4.4, contract 3.5.3).

``channel`` and ``kinds`` carry lowercase enum values on the wire (3.0.2).
"""

from pydantic import BaseModel, ConfigDict, Field

from modules.backend.models.notification import NotificationKind
from modules.backend.models.user_channel_identity import ChannelKind


class NotificationRecipientCreate(BaseModel):
    """POST /missions/{id}/notification-recipients body.

    ``kinds`` omitted or null subscribes to notifications.default_kinds.
    """

    model_config = ConfigDict(extra="forbid")

    user_email: str = Field(..., min_length=3, max_length=255)
    channel: ChannelKind
    kinds: list[NotificationKind] | None = Field(default=None, min_length=1)


class NotificationRecipientResponse(BaseModel):
    """One recipient of a mission's notifications."""

    id: str
    user_id: str
    user_email: str
    channel: ChannelKind
    kinds: list[NotificationKind]


class NotificationRecipientListResponse(BaseModel):
    """GET /missions/{id}/notification-recipients response data."""

    recipients: list[NotificationRecipientResponse]
