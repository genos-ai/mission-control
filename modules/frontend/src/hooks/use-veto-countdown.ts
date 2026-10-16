import { useEffect, useState } from 'react'

export interface VetoState {
  /** Whole seconds remaining until the window expires. 0 when expired. */
  remainingSec: number
  /** True once the timestamp has passed — veto is no longer available. */
  expired: boolean
}

/**
 * Live countdown for an ai_assisted auto-approval veto window (Plan 42 §4.4).
 *
 * Returns null when `vetoExpiresAt` is null/undefined (no window — the
 * task is a manual approval, not a Director auto-approval). Otherwise
 * ticks every second until expiry, then stops and returns expired: true.
 *
 * One interval per active countdown, auto-cleared on unmount or when the
 * input timestamp changes.
 */
export function useVetoCountdown(
  vetoExpiresAt: string | null | undefined,
): VetoState | null {
  const [now, setNow] = useState<number>(() => Date.now())

  useEffect(() => {
    if (!vetoExpiresAt) return
    const expiry = new Date(vetoExpiresAt).getTime()
    if (Date.now() >= expiry) return // already expired — no timer needed
    const interval = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [vetoExpiresAt])

  if (!vetoExpiresAt) return null
  const expiry = new Date(vetoExpiresAt).getTime()
  const remainingMs = expiry - now
  return {
    remainingSec: Math.max(0, Math.ceil(remainingMs / 1000)),
    expired: remainingMs <= 0,
  }
}
