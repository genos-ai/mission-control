"""Plan 88 Phase 4 config schema rules."""

from typing import get_args

import pytest
from pydantic import ValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import (
    NotificationKindValue,
    NotificationsSchema,
)
from modules.backend.models.notification import NotificationKind


def test_notification_kind_literal_matches_enum() -> None:
    assert set(get_args(NotificationKindValue)) == {k.value for k in NotificationKind}


def test_default_kinds_load_from_yaml() -> None:
    kinds = get_app_config().notifications.default_kinds
    assert [NotificationKind(k) for k in kinds] == list(NotificationKind)


def test_default_kinds_required_and_known() -> None:
    with pytest.raises(ValidationError):
        NotificationsSchema()
    with pytest.raises(ValidationError):
        NotificationsSchema(default_kinds=[])
    with pytest.raises(ValidationError):
        NotificationsSchema(default_kinds=["RUN_FAILED"])
