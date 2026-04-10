"""
Mission Plan Daemon (Plan 42 §10.8, Phase 5).

Background asyncio task that polls for plans in autonomous modes and
dispatches their approved tasks without user intervention. Also serves
as the expiry cut-off for ai_assisted veto windows — tasks with a
past `veto_expires_at` become eligible for dispatch alongside
explicitly-approved ones.

Scope (kept intentionally narrow):

    - Runs as one asyncio task per backend process.
    - Started by FastAPI lifespan when the
      `experimental_mission_plan_daemon_enabled` feature flag is true.
    - Polls every `poll_interval_seconds` (default 5).
    - For each active mission_plan with gate_mode in {autonomous, off}
      that has at least one approved task with resolved deps, attempts
      to dispatch via MissionPlanService.dispatch_approved.
    - Uses a per-plan Redis lock (SET NX PX) so multiple daemon
      instances in a multi-process deploy don't double-dispatch.
    - Catches exceptions per plan — one failing plan can't kill the
      daemon or affect other plans.
    - Graceful shutdown on CancelledError.

Not in scope (intentionally deferred):

    - Production-grade reliability (Temporal workflow migration
      — see Plan 16).
    - Budget enforcement across concurrent dispatches — relies on
      MissionPlanService.dispatch_approved's own cumulative check.
    - Activity digests (Plan 42 Phase 5 deliverable item 3) — logged
      per dispatch, but no daily summary rollup yet.

Config gate: off by default. Explicitly enable in features.yaml:
    experimental_mission_plan_daemon_enabled: true
"""

from __future__ import annotations

import asyncio
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select

from modules.backend.core.config import get_redis_url
from modules.backend.core.database import get_session_factory
from modules.backend.core.logging import get_logger
from modules.backend.models.mission_plan import (
    MissionPlan,
    MissionPlanStatus,
    PlanTaskStatus,
)
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.services.mission_plan import MissionPlanService

logger = get_logger(__name__)


# Gate modes that receive continuous autonomous dispatch from the daemon.
# ai_assisted does NOT — that mode relies on the user clicking Run
# manually, the daemon just provides the veto-window timestamp reference.
_AUTONOMOUS_GATE_MODES = frozenset({"autonomous", "off"})

# Redis lock key template. Per-plan so concurrent plans don't block
# each other, but same plan across instances serialises.
_LOCK_KEY_TEMPLATE = "mission_plan_daemon:lock:{plan_id}"
_LOCK_TTL_MS = 30_000  # 30s — longer than a single dispatch cycle

# Default poll interval. Low enough that users see autonomous runs
# progress promptly, high enough to avoid hammering the DB.
_DEFAULT_POLL_INTERVAL_SEC = 5.0


class MissionPlanDaemon:
    """Background asyncio task that dispatches autonomous plans.

    Instantiated at FastAPI startup, runs until shutdown. One instance
    per backend process; multiple processes coordinate through Redis
    locks per plan.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SEC,
    ) -> None:
        self._redis_url = redis_url or get_redis_url()
        self._poll_interval = poll_interval_seconds
        self._redis: AsyncRedis | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the background task. Safe to call only once per instance."""
        if self._task is not None:
            logger.warning("MissionPlanDaemon already started — ignoring")
            return
        self._redis = AsyncRedis.from_url(self._redis_url)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_forever(), name="mission_plan_daemon")
        logger.info(
            "MissionPlanDaemon started",
            extra={"poll_interval_sec": self._poll_interval},
        )

    async def stop(self) -> None:
        """Signal shutdown and wait for the task to drain.

        Any in-flight dispatch runs to completion; the daemon just stops
        picking up new work. If the task takes longer than 60 seconds
        to drain it's force-cancelled.
        """
        if self._task is None:
            return
        logger.info("MissionPlanDaemon stopping")
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=60.0)
        except asyncio.TimeoutError:
            logger.warning("MissionPlanDaemon did not drain in 60s — cancelling")
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        finally:
            if self._redis is not None:
                await self._redis.aclose()
                self._redis = None
            self._task = None
            logger.info("MissionPlanDaemon stopped")

    # ── Poll loop ──────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Main loop: wake every poll_interval, scan plans, dispatch ready ones."""
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.error("MissionPlanDaemon tick failed", exc_info=True)
            # Sleep with early-exit if stop signalled
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
                return  # stop was signalled during sleep
            except asyncio.TimeoutError:
                continue  # normal poll cycle — loop again

    async def _tick(self) -> None:
        """One pass: find autonomous plans with work ready, dispatch each."""
        plan_ids = await self._find_ready_plan_ids()
        if not plan_ids:
            return

        logger.debug(
            "MissionPlanDaemon found ready plans",
            extra={"ready_plan_count": len(plan_ids)},
        )

        for plan_id in plan_ids:
            if self._stop_event.is_set():
                return  # graceful shutdown mid-tick
            await self._try_dispatch_plan(plan_id)

    async def _find_ready_plan_ids(self) -> list[str]:
        """Query for autonomous plans that have at least one approved task.

        Returns a list of mission_plan ids whose gate_mode is in
        {autonomous, off}, status is active, and which have at least
        one plan_task_state row in approved status. The `dispatch_approved`
        call later verifies dep closure and budget headroom — this is
        just a cheap pre-filter.
        """
        sf = get_session_factory()
        async with sf() as db:
            q = (
                select(MissionPlan.id)
                .where(
                    MissionPlan.status == MissionPlanStatus.ACTIVE.value,
                    MissionPlan.gate_mode.in_(_AUTONOMOUS_GATE_MODES),
                )
            )
            result = await db.execute(q)
            candidate_ids = [row[0] for row in result.all()]

            if not candidate_ids:
                return []

            # Filter to plans with at least one approved task.
            repo = MissionPlanRepository(db)
            ready: list[str] = []
            for plan_id in candidate_ids:
                approved = await repo.get_task_states(
                    plan_id, status=PlanTaskStatus.APPROVED,
                )
                if approved:
                    ready.append(plan_id)
            return ready

    async def _try_dispatch_plan(self, plan_id: str) -> None:
        """Acquire the per-plan lock and dispatch if successful.

        If another instance holds the lock (or already dispatched in
        this cycle), skip silently. Lock TTL ensures stale locks don't
        block forever if a holder crashes.
        """
        lock_key = _LOCK_KEY_TEMPLATE.format(plan_id=plan_id)
        assert self._redis is not None
        acquired = await self._redis.set(
            lock_key, "1", nx=True, px=_LOCK_TTL_MS,
        )
        if not acquired:
            logger.debug(
                "MissionPlanDaemon skipping locked plan",
                extra={"plan_id": plan_id},
            )
            return

        try:
            sf = get_session_factory()
            async with sf() as db:
                # Daemon-driven dispatches don't have a requesting user
                # identity — use the mission owner as the actor, same
                # pattern the Director's approve_plan_tasks tool uses.
                from modules.backend.repositories.mission_plan import (
                    MissionPlanRepository,
                )
                from modules.backend.services.mission import MissionService

                repo = MissionPlanRepository(db)
                plan = await repo.get_by_id(plan_id)

                mission_svc = MissionService(db)
                mission = await mission_svc.get_mission(plan.mission_id)

                svc = MissionPlanService(db)
                result = await svc.dispatch_approved(
                    plan_id, user_id=mission.owner_id,
                )
                await db.commit()
                logger.info(
                    "MissionPlanDaemon dispatched plan",
                    extra={
                        "plan_id": plan_id,
                        "outcome_status": result.get("outcome_status"),
                        "execution_record_id": result.get("execution_record_id"),
                        "dispatched_task_count": len(result.get("dispatched_task_ids") or []),
                        "run_cost_usd": result.get("total_cost_usd"),
                    },
                )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "MissionPlanDaemon dispatch failed",
                extra={"plan_id": plan_id, "error": str(e)},
                exc_info=True,
            )
        finally:
            # Best-effort lock release. The TTL protects us if this
            # fails — worst case the plan waits _LOCK_TTL_MS before
            # being eligible again.
            try:
                await self._redis.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass


# ── Module-level singleton for lifespan integration ───────────────────────


_daemon: MissionPlanDaemon | None = None


def get_daemon() -> MissionPlanDaemon | None:
    """Return the currently-running daemon instance, or None."""
    return _daemon


async def start_daemon(**kwargs: Any) -> MissionPlanDaemon:
    """Create + start the process-wide daemon instance.

    Called once from FastAPI lifespan when the feature flag is enabled.
    """
    global _daemon
    if _daemon is not None:
        logger.warning("start_daemon called but daemon already running")
        return _daemon
    _daemon = MissionPlanDaemon(**kwargs)
    await _daemon.start()
    return _daemon


async def stop_daemon() -> None:
    """Gracefully stop the process-wide daemon instance."""
    global _daemon
    if _daemon is None:
        return
    await _daemon.stop()
    _daemon = None
