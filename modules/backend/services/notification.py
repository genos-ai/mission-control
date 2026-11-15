"""
Notification Service (Plan 88 step 88.4.4, contracts 3.5.1, 3.1.10 and 3.6.2).

Delivers mission notifications to each subscribed recipient's confirmed
channel identity, never to a broadcast list. notification_deliveries is the
audit and idempotency record: one row per (kind, subject, recipient, channel),
and a SENT row is never sent again, so an activity retry only re-attempts the
recipients that failed. Every stored or emitted error passes through
redact_secrets, because aiogram error text can carry the bot token.

Gate notifications carry Approve and Reject buttons only when inbound
approvals are enabled, the recipient is a mission operator at send time and
the request names its gate. Each button carries a fresh single-use token.

Every notification is also published to the Redis channel
notify:mission:{mission_id} for the web.
"""

import json
import uuid
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config, get_redis_url
from modules.backend.core.config_schema import NotificationsSchema
from modules.backend.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from modules.backend.core.logging import get_logger
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.core.redaction import redact_secrets
from modules.backend.core.utils import utc_now
from modules.backend.events.mission_run_types import NotificationDeliveryFailedEvent
from modules.backend.gateway.adapters.telegram import TelegramAdapter
from modules.backend.gateway.registry import get_adapter
from modules.backend.models.action_token import ActionTokenPurpose
from modules.backend.models.mission_run import MissionRunStatus
from modules.backend.models.notification import (
    MissionNotificationRecipient,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationKind,
)
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.mission import (
    MissionMemberRepository,
    MissionRepository,
)
from modules.backend.repositories.mission_notification_recipient import (
    MissionNotificationRecipientRepository,
)
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.notification_delivery import (
    NotificationDeliveryRepository,
)
from modules.backend.repositories.user import UserRepository
from modules.backend.schemas.notification import (
    NotificationRecipientCreate,
    NotificationRecipientResponse,
)
from modules.backend.services.action_token import ActionTokenService
from modules.backend.services.base import BaseService
from modules.backend.services.channel_identity import ChannelIdentityService
from modules.backend.services.mission import MissionService
from modules.backend.temporal.mission_run_models import NotificationRequest

logger = get_logger(__name__)

GATE_KINDS = frozenset(
    {
        NotificationKind.GATE_WAITING,
        NotificationKind.GATE_ESCALATED,
        NotificationKind.GATE_TIMEOUT_PAUSED,
    }
)

# One fixed headline and SSE level per kind (contract 3.6.2).
_HEADLINES: dict[NotificationKind, tuple[str, str]] = {
    NotificationKind.RUN_SUCCEEDED: ("Run succeeded", "success"),
    NotificationKind.RUN_FAILED: ("Run failed", "error"),
    NotificationKind.GATE_WAITING: ("Gate waiting for a decision", "warning"),
    NotificationKind.GATE_ESCALATED: (
        "Gate escalated: still waiting for a decision",
        "warning",
    ),
    NotificationKind.GATE_TIMEOUT_PAUSED: (
        "Gate timed out: mission paused until the gate is decided",
        "error",
    ),
    NotificationKind.BUDGET_PAUSED: ("Budget cap reached: mission paused", "error"),
    NotificationKind.RUN_SKIPPED: ("Scheduled run skipped", "warning"),
    NotificationKind.RUN_MISSED: ("Scheduled runs missed", "warning"),
}

_MISSING = "-"


def _field(payload: dict, run_fields: dict, key: str) -> Any:
    """The payload value, else the run row's, else None."""
    value = payload.get(key)
    return value if value is not None else run_fields.get(key)


def _render(kind: NotificationKind, mission_name: str, payload: dict) -> str:
    """The message text for a kind: one fixed template per kind.

    Every message names the mission, the run sequence, the status and the cost;
    run-finished messages also state the digest generator. payload holds the
    request payload merged over the run row's sequence, status and cost.
    """
    headline, _ = _HEADLINES[kind]
    sequence = payload.get("sequence")
    cost = payload.get("cost_usd")
    lines = [
        headline,
        f"Mission: {mission_name}",
        f"Run: {f'#{sequence}' if sequence is not None else _MISSING}",
        f"Status: {payload.get('status') or _MISSING}",
        f"Cost: {f'${float(cost):.4f}' if cost is not None else _MISSING}",
    ]
    if payload.get("reason"):
        lines.append(f"Reason: {payload['reason']}")
    if kind == NotificationKind.RUN_FAILED and payload.get("detail"):
        lines.append(f"Detail: {payload['detail']}")
    if kind in (NotificationKind.RUN_SUCCEEDED, NotificationKind.RUN_FAILED):
        lines.append(f"Digest: {payload.get('digest_generator') or 'none'}")
        if payload.get("digest_summary"):
            lines.append(str(payload["digest_summary"]))
    if kind in GATE_KINDS and payload.get("gate_point"):
        lines.append(f"Gate: {payload['gate_point']}")
    if kind == NotificationKind.BUDGET_PAUSED and payload.get("cap"):
        lines.append(f"Cap: {payload['cap']}")
    if kind == NotificationKind.RUN_MISSED and payload.get("count") is not None:
        lines.append(f"Missed slots: {payload['count']}")
    return "\n".join(lines)


async def _publish_sse(mission_id: str, message: dict) -> None:
    """Publish to notify:mission:{mission_id}. Best-effort: the web view is secondary."""
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        await redis.publish(f"notify:mission:{mission_id}", json.dumps(message, default=str))
    except (RedisError, OSError):
        # best-effort: Telegram delivery and the delivery rows do not depend on SSE.
        logger.warning(
            "notification SSE publish failed",
            extra={"mission_id": mission_id},
            exc_info=True,
        )
    finally:
        await redis.aclose()


def _telegram_adapter(config: NotificationsSchema) -> TelegramAdapter | None:
    """The Telegram adapter, or None when notifications or the channel are disabled."""
    if not config.enabled or not config.channels.telegram.enabled:
        return None
    adapter = get_adapter(ChannelKind.TELEGRAM.value)
    return adapter if isinstance(adapter, TelegramAdapter) else None


class NotificationService(BaseService):
    """Per-mission notifications: delivery, ad-hoc messages and recipients."""

    def __init__(self, session: AsyncSession, event_bus: EventBusProtocol | None = None) -> None:
        super().__init__(session)
        self._event_bus = event_bus
        self._recipients = MissionNotificationRecipientRepository(session)
        self._deliveries = NotificationDeliveryRepository(session)
        self._missions = MissionRepository(session)
        self._members = MissionMemberRepository(session)
        self._runs = MissionRunRepository(session)
        self._users = UserRepository(session)
        self._identities = ChannelIdentityService(session)
        self._tokens = ActionTokenService(session)

    # ── Delivery ─────────────────────────────────────────────────────────

    async def notify(self, request: NotificationRequest) -> list[NotificationDelivery]:
        """Deliver one notification to every recipient subscribed to its kind.

        Commits after each recipient, so a SENT row survives a later failure.
        Raises ExternalServiceError after all recipients when any delivery
        failed, so the activity retry covers the failed recipients only.
        """
        if self._event_bus is None:
            raise RuntimeError("NotificationService.notify requires an event bus")
        kind = NotificationKind(request.kind)
        config = get_app_config().notifications
        mission = await self._missions.get_by_id(request.mission_id)
        payload = await self._payload(request)
        text = _render(kind, mission.name, payload)

        recipients = await self._recipients.list_for_kind(request.mission_id, kind)
        adapter = _telegram_adapter(config) if recipients else None
        deliveries: list[NotificationDelivery] = []
        failed = 0
        for recipient in recipients:
            delivery, ok = await self._deliver(request, kind, recipient, text, adapter, config)
            deliveries.append(delivery)
            failed += 0 if ok else 1

        headline, level = _HEADLINES[kind]
        await _publish_sse(
            request.mission_id,
            {
                "type": level,
                "kind": kind.value,
                "title": headline,
                "body": text,
                "data": {
                    "mission_id": request.mission_id,
                    "mission_run_id": request.mission_run_id,
                    "gate_request_id": request.gate_request_id,
                    "subject_id": request.subject_id,
                    **request.payload,
                },
            },
        )
        if failed:
            raise ExternalServiceError(f"{failed} notification deliveries failed")
        return deliveries

    async def _payload(self, request: NotificationRequest) -> dict:
        """The request payload over the run's sequence, status and cost, when it names a run."""
        run_fields: dict = {}
        if request.mission_run_id is not None:
            run = await self._runs.get_by_id_or_none(request.mission_run_id)
            if run is not None:
                run_fields = {
                    "sequence": run.sequence,
                    "status": MissionRunStatus(run.status).value,
                    "cost_usd": run.cost_usd,
                }
        merged = dict(request.payload)
        for key in ("sequence", "status", "cost_usd"):
            merged[key] = _field(request.payload, run_fields, key)
        return merged

    async def _deliver(
        self,
        request: NotificationRequest,
        kind: NotificationKind,
        recipient: MissionNotificationRecipient,
        text: str,
        adapter: TelegramAdapter | None,
        config: NotificationsSchema,
    ) -> tuple[NotificationDelivery, bool]:
        """Deliver to one recipient; returns the row and False when the send failed."""
        channel = ChannelKind(recipient.channel)
        recipient_user_id = str(recipient.user_id)
        delivery = await self._deliveries.get_or_create(
            dedupe_key=f"{kind.value}:{request.subject_id}:{recipient_user_id}:{channel.value}",
            mission_id=request.mission_id,
            mission_run_id=request.mission_run_id,
            kind=kind,
            recipient_user_id=recipient_user_id,
            channel=channel,
        )
        if delivery.status == NotificationDeliveryStatus.SENT:
            return delivery, True
        if adapter is None:
            return await self._settle(delivery, NotificationDeliveryStatus.SKIPPED_DISABLED), True
        identity = await self._identities.get_for_user(recipient_user_id, channel)
        if identity is None:
            return (
                await self._settle(delivery, NotificationDeliveryStatus.SKIPPED_NO_IDENTITY),
                True,
            )

        actions, raw_tokens = await self._gate_actions(request, kind, recipient_user_id, config)
        delivery.attempt_count += 1
        # Tokens are committed before their buttons exist anywhere, so a delivered
        # button never points at a missing token.
        await self._session.commit()
        try:
            ref = await adapter.send_notification(int(identity.external_id), text, actions)
        except Exception as exc:
            # Catch-all justified: aiogram and aiohttp raise from an unbounded set
            # (API errors, network, timeouts). The failure is recorded per recipient
            # and re-raised as ExternalServiceError after the other recipients.
            return await self._record_failure(delivery, kind, channel, exc), False

        delivery.status = NotificationDeliveryStatus.SENT
        delivery.sent_at = utc_now()
        delivery.provider_message_ref = ref
        delivery.error = None
        if raw_tokens:
            await self._tokens.set_message_ref(raw_tokens, ref)
        await self._session.commit()
        return delivery, True

    async def _settle(
        self, delivery: NotificationDelivery, status: NotificationDeliveryStatus
    ) -> NotificationDelivery:
        delivery.status = status
        await self._session.commit()
        return delivery

    async def _record_failure(
        self,
        delivery: NotificationDelivery,
        kind: NotificationKind,
        channel: ChannelKind,
        exc: Exception,
    ) -> NotificationDelivery:
        error = redact_secrets(str(exc) or type(exc).__name__)
        delivery.status = NotificationDeliveryStatus.FAILED
        delivery.error = error
        await self._session.commit()
        logger.warning(
            "notification delivery failed",
            extra={
                "mission_id": delivery.mission_id,
                "delivery_id": delivery.id,
                "kind": kind.value,
                "error": error,
            },
        )
        await self._event_bus.publish_to_mission(
            delivery.mission_id,
            NotificationDeliveryFailedEvent(
                session_id=uuid.UUID(str(delivery.mission_id)),
                source="notification_service",
                mission_id=delivery.mission_id,
                mission_run_id=delivery.mission_run_id,
                delivery_id=str(delivery.id),
                kind=kind.value,
                channel=channel.value,
                error=error,
            ),
        )
        return delivery

    async def _gate_actions(
        self,
        request: NotificationRequest,
        kind: NotificationKind,
        recipient_user_id: str,
        config: NotificationsSchema,
    ) -> tuple[list[tuple[str, str]] | None, list[str]]:
        """Approve and Reject buttons with fresh tokens, when this recipient may decide."""
        if (
            kind not in GATE_KINDS
            or not config.channels.telegram.inbound_approvals_enabled
            or request.gate_request_id is None
        ):
            return None, []
        user = await self._users.get_by_id_or_none(recipient_user_id)
        if user is None or not await MissionService(self._session).is_operator(
            request.mission_id, user
        ):
            return None, []
        raw_tokens = [
            await self._tokens.issue(
                purpose=ActionTokenPurpose.GATE_DECISION,
                user_id=recipient_user_id,
                channel=ChannelKind.TELEGRAM,
                gate_request_id=request.gate_request_id,
                ttl_seconds=config.action_tokens.gate_decision_ttl_seconds,
            )
            for _ in range(2)
        ]
        approve, reject = raw_tokens
        return [("Approve", f"g:{approve}:a"), ("Reject", f"g:{reject}:r")], raw_tokens

    # ── Ad-hoc messages ──────────────────────────────────────────────────

    async def send_ad_hoc(self, mission_id: str, title: str, body: str, level: str) -> None:
        """Publish SSE and send Telegram to the mission's confirmed TELEGRAM recipients.

        For workflow-run and human-input messages. No delivery row and no
        dedupe; failures are logged redacted and never raised.
        """
        await _publish_sse(
            mission_id,
            {
                "type": level,
                "title": title,
                "body": body,
                "data": {"mission_id": mission_id},
            },
        )
        text = f"{title}\n\n{body}"
        try:
            adapter = _telegram_adapter(get_app_config().notifications)
            if adapter is None:
                return
            recipients = await self._recipients.list_by_mission(mission_id, ChannelKind.TELEGRAM)
            for recipient in recipients:
                identity = await self._identities.get_for_user(
                    str(recipient.user_id), ChannelKind.TELEGRAM
                )
                if identity is not None:
                    await self._send_ad_hoc_one(adapter, mission_id, identity.external_id, text)
        except (SQLAlchemyError, RuntimeError, OSError) as exc:
            # best-effort: an ad-hoc message never fails the workflow step that sent it.
            logger.warning(
                "ad-hoc notification failed",
                extra={"mission_id": mission_id, "error": redact_secrets(str(exc))},
            )

    @staticmethod
    async def _send_ad_hoc_one(
        adapter: TelegramAdapter, mission_id: str, external_id: str, text: str
    ) -> None:
        try:
            await adapter.send_notification(int(external_id), text, None)
        except Exception as exc:
            # Catch-all justified: aiogram and aiohttp raise from an unbounded set.
            # best-effort: one recipient's failure does not stop the others.
            logger.warning(
                "ad-hoc notification delivery failed",
                extra={"mission_id": mission_id, "error": redact_secrets(str(exc))},
            )

    # ── Recipients ───────────────────────────────────────────────────────

    async def list_recipients(self, mission_id: str) -> list[NotificationRecipientResponse]:
        """The mission's recipients, oldest first, each with the user's email."""
        await self._missions.get_by_id(mission_id)
        recipients = await self._recipients.list_by_mission(mission_id)
        return [await self._to_response(r) for r in recipients]

    async def add_recipient(
        self, mission_id: str, data: NotificationRecipientCreate, actor_id: str
    ) -> NotificationRecipientResponse:
        """Subscribe the owner or a member of the mission, by email."""
        mission = await self._missions.get_by_id(mission_id)
        user = await self._users.get_by_email(data.user_email.strip())
        if user is None:
            raise NotFoundError("No user with that email")
        user_id = str(user.id)
        if mission.owner_id != user_id and (
            await self._members.get_membership(mission_id, user_id) is None
        ):
            raise ValidationError("A recipient must be the mission owner or a mission member")
        kinds = data.kinds or [
            NotificationKind(k) for k in get_app_config().notifications.default_kinds
        ]
        try:
            async with self._session.begin_nested():
                recipient = await self._recipients.create(
                    mission_id=mission_id,
                    user_id=user_id,
                    channel=data.channel,
                    kinds=[k.value for k in dict.fromkeys(kinds)],
                )
        except IntegrityError as exc:
            raise ConflictError("That user already receives this mission's notifications") from exc
        await self._session.commit()
        self._log_operation(
            "notification recipient added",
            mission_id=mission_id,
            recipient_id=str(recipient.id),
            actor_id=actor_id,
        )
        return NotificationRecipientResponse(
            id=str(recipient.id),
            user_id=user_id,
            user_email=user.email,
            channel=ChannelKind(recipient.channel),
            kinds=[NotificationKind(k) for k in recipient.kinds],
        )

    async def remove_recipient(self, mission_id: str, recipient_id: str, actor_id: str) -> None:
        """Remove a recipient of this mission; another mission's recipient is NotFoundError."""
        recipient = await self._recipients.get_for_mission(mission_id, recipient_id)
        if recipient is None:
            raise NotFoundError("Notification recipient not found")
        await self._session.delete(recipient)
        await self._session.commit()
        self._log_operation(
            "notification recipient removed",
            mission_id=mission_id,
            recipient_id=recipient_id,
            actor_id=actor_id,
        )

    async def _to_response(
        self, recipient: MissionNotificationRecipient
    ) -> NotificationRecipientResponse:
        user = await self._users.get_by_id(recipient.user_id)
        return NotificationRecipientResponse(
            id=str(recipient.id),
            user_id=str(recipient.user_id),
            user_email=user.email,
            channel=ChannelKind(recipient.channel),
            kinds=[NotificationKind(k) for k in recipient.kinds],
        )
