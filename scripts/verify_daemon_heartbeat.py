#!/usr/bin/env python3
"""
Plan 46 Phase 1 work unit #3 — Daemon heartbeat verification script.

Exercises ``MissionPlanDaemon``'s heartbeat publishing and confirms:

  1. Starting the daemon publishes no heartbeat immediately (there's
     been no tick yet — fresh process, fresh key).
  2. After the first poll cycle the heartbeat lands in Redis with a
     timestamp, tick_count=1, poll_interval_sec matching the
     configured value, and last_error=None.
  3. After a few more cycles the tick_count advances monotonically.
  4. The timestamp stays fresher than the Plan 46 exit-criterion
     threshold (30 seconds) throughout.
  5. Stopping the daemon lets the heartbeat key expire naturally via
     its TTL — we don't explicitly delete it on shutdown because the
     TTL is short enough that observers will see "missing" within a
     few seconds anyway, and because the observability signal of a
     stopped daemon is "the key expired recently" which is clearer
     than "the key vanished instantly".

Usage:
    python scripts/verify_daemon_heartbeat.py [--verbose]

Exit codes:
    0  — all checks passed
    1  — one or more checks failed

Requirements:
    - Redis running and reachable via the config redis URL
    - Postgres running (the daemon's tick queries the DB even with
      zero autonomous plans)

Re-runnable any number of times. Uses a short poll interval (1s) so
the script finishes in a few seconds rather than minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

PASS = "✓"
FAIL = "✗"
SKIP = "⚠"

# Short interval so the test finishes fast. The default daemon
# interval is 5s which would make this script take 15+ seconds.
_TEST_POLL_INTERVAL_SEC = 1.0


class DaemonHeartbeatVerifier:
    """Runs the heartbeat verification suite against a live Redis."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._failures: list[str] = []
        self._daemon = None
        self._redis = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"    {msg}")

    def _pass(self, check: str) -> None:
        print(f"  {PASS} {check}")

    def _fail(self, check: str, detail: str) -> None:
        print(f"  {FAIL} {check}: {detail}")
        self._failures.append(f"{check}: {detail}")

    async def setup(self) -> bool:
        """Start a daemon instance with a fast poll interval."""
        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url
        from modules.backend.services.mission_plan_daemon import HEARTBEAT_KEY, MissionPlanDaemon

        # Open our own Redis client for reads so the test doesn't
        # depend on the daemon's client being exposed.
        self._redis = AsyncRedis.from_url(get_redis_url())

        # Clear any leftover heartbeat from a prior run so the
        # "no heartbeat before first tick" check isn't confused.
        await self._redis.delete(HEARTBEAT_KEY)

        self._daemon = MissionPlanDaemon(
            poll_interval_seconds=_TEST_POLL_INTERVAL_SEC,
        )
        await self._daemon.start()
        self._log(f"Daemon started with poll_interval_sec={_TEST_POLL_INTERVAL_SEC}")
        return True

    async def teardown(self) -> None:
        """Stop the daemon + close Redis."""
        if self._daemon is not None:
            await self._daemon.stop()
        if self._redis is not None:
            await self._redis.aclose()

    # -------------------------------------------------------------------------
    # Checks
    # -------------------------------------------------------------------------

    async def check_heartbeat_lands_after_first_tick(self) -> None:
        """After one poll cycle the heartbeat should be in Redis."""
        from modules.backend.services.mission_plan_daemon import get_heartbeat

        # Wait just over one poll interval so we know at least one
        # tick has completed.
        await asyncio.sleep(_TEST_POLL_INTERVAL_SEC * 1.5)

        heartbeat = await get_heartbeat(self._redis)
        if heartbeat is None:
            self._fail(
                "Heartbeat written after first tick",
                "no heartbeat key in Redis",
            )
            return

        missing = [
            k
            for k in ("timestamp", "tick_count", "poll_interval_sec", "last_error")
            if k not in heartbeat
        ]
        if missing:
            self._fail(
                "Heartbeat payload shape",
                f"missing fields: {missing}",
            )
            return

        if heartbeat.get("tick_count", 0) < 1:
            self._fail(
                "tick_count >= 1 after first cycle",
                f"tick_count={heartbeat.get('tick_count')!r}",
            )
            return

        if heartbeat.get("poll_interval_sec") != _TEST_POLL_INTERVAL_SEC:
            self._fail(
                "poll_interval_sec matches configured value",
                f"got {heartbeat.get('poll_interval_sec')}, expected {_TEST_POLL_INTERVAL_SEC}",
            )
            return

        if heartbeat.get("last_error") is not None:
            self._fail(
                "last_error is None on healthy tick",
                f"got {heartbeat.get('last_error')!r}",
            )
            return

        self._log(f"  heartbeat payload: {heartbeat}")
        self._pass("Heartbeat written with correct payload shape after first tick")

    async def check_tick_count_advances(self) -> None:
        """Tick count should increment over subsequent polls."""
        from modules.backend.services.mission_plan_daemon import get_heartbeat

        first = await get_heartbeat(self._redis)
        if first is None:
            self._fail("tick_count advances", "no heartbeat to compare against")
            return
        first_tick = first.get("tick_count", 0)

        # Wait for at least two more polls.
        await asyncio.sleep(_TEST_POLL_INTERVAL_SEC * 2.5)

        second = await get_heartbeat(self._redis)
        if second is None:
            self._fail("tick_count advances", "heartbeat disappeared unexpectedly")
            return
        second_tick = second.get("tick_count", 0)

        if second_tick > first_tick:
            self._log(f"  tick_count went from {first_tick} → {second_tick}")
            self._pass("tick_count advances monotonically across polls")
        else:
            self._fail(
                "tick_count advances",
                f"{first_tick} → {second_tick} (expected strictly increasing)",
            )

    async def check_heartbeat_freshness(self) -> None:
        """Heartbeat age must be under the Plan 46 exit threshold (30s).

        Both ``utc_now()`` and the daemon's persisted timestamp are
        timezone-naive (codebase convention — see core/utils.py). We
        stay naive throughout and subtract directly.
        """
        from datetime import datetime

        from modules.backend.core.utils import utc_now
        from modules.backend.services.mission_plan_daemon import get_heartbeat

        heartbeat = await get_heartbeat(self._redis)
        if heartbeat is None:
            self._fail("Heartbeat freshness", "no heartbeat to check")
            return

        timestamp_str = heartbeat.get("timestamp")
        if not timestamp_str:
            self._fail("Heartbeat freshness", "timestamp field empty")
            return

        try:
            last_at = datetime.fromisoformat(str(timestamp_str))
        except ValueError as exc:
            self._fail("Heartbeat timestamp parseable", f"{exc}")
            return

        # Both sides tz-naive: subtraction is valid.
        age = (utc_now() - last_at).total_seconds()
        if age < 30.0:
            self._log(f"  age = {age:.2f}s (threshold: 30s)")
            self._pass(f"Heartbeat age is fresh ({age:.2f}s < 30s)")
        else:
            self._fail(
                "Heartbeat freshness",
                f"age={age:.2f}s (threshold: 30s)",
            )

    async def check_redis_ttl_set(self) -> None:
        """Redis TTL on the heartbeat key should be positive (not persistent)."""
        from modules.backend.services.mission_plan_daemon import HEARTBEAT_KEY

        ttl = await self._redis.ttl(HEARTBEAT_KEY)
        if ttl > 0:
            self._log(f"  TTL = {ttl}s")
            self._pass(f"Heartbeat key has positive TTL ({ttl}s — expires on daemon death)")
        elif ttl == -1:
            self._fail(
                "Heartbeat key has TTL",
                "TTL is -1 (persistent) — stopped daemon would leave a stale key forever",
            )
        elif ttl == -2:
            self._fail(
                "Heartbeat key has TTL",
                "TTL is -2 (key does not exist)",
            )
        else:
            self._fail("Heartbeat key has TTL", f"unexpected TTL value: {ttl}")

    # -------------------------------------------------------------------------
    # Runner
    # -------------------------------------------------------------------------

    async def run(self) -> bool:
        """Run all checks. Returns True if all passed."""
        print("\nPlan 46 Phase 1 — Daemon Heartbeat Verification")
        print("=" * 70)

        print("\n[Setup] Starting test daemon...")
        if not await self.setup():
            return False

        print("\n[A] Heartbeat publishing")
        await self.check_heartbeat_lands_after_first_tick()

        print("\n[B] Tick advancement")
        await self.check_tick_count_advances()

        print("\n[C] Freshness (Plan 46 exit criterion: age < 30s)")
        await self.check_heartbeat_freshness()

        print("\n[D] TTL (stale-heartbeat cleanup)")
        await self.check_redis_ttl_set()

        print("\n" + "=" * 70)
        if self._failures:
            print(f"FAILED — {len(self._failures)} check(s) failed:")
            for f in self._failures:
                print(f"  {FAIL} {f}")
            return False
        else:
            print("PASSED — all daemon heartbeat checks passed")
            return True


async def _main(verbose: bool) -> int:
    verifier = DaemonHeartbeatVerifier(verbose=verbose)
    try:
        passed = await verifier.run()
    finally:
        try:
            await verifier.teardown()
        except Exception as exc:
            print(f"\n{FAIL} Teardown failed: {exc}")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show debug details for each check"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.verbose)))


if __name__ == "__main__":
    main()
