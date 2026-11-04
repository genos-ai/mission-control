import { useEffect, useRef, useCallback, useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { API_BASE } from '@/lib/constants'
import type { SseEvent } from '@/types'

/**
 * Parse an SSE text stream from a fetch Response.
 *
 * Yields parsed events as they arrive. Handles the `event:` and `data:`
 * fields per the SSE spec. Reconnection is handled by the caller.
 */
export async function* parseSseStream(
  response: Response,
  signal: AbortSignal,
): AsyncGenerator<{ event: string | null; data: string }> {
  const reader = response.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      let currentEvent: string | null = null
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          yield { event: currentEvent, data: line.slice(6) }
          currentEvent = null
        } else if (line === '') {
          currentEvent = null
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Core SSE connection using fetch + ReadableStream.
 *
 * Uses Authorization header (no token-in-URL hack). Reconnects
 * automatically with exponential backoff on network errors. Each
 * reconnect reads a fresh JWT from the auth store.
 */
function useFetchSse(
  path: string | null,
  maxEvents: number,
) {
  const [events, setEvents] = useState<SseEvent[]>([])
  const [connected, setConnected] = useState(false)
  // totalAdded counts every event ever received, uncapped by maxEvents.
  // Callers use this to detect new events even when the ring buffer is full
  // and sseEvents.length stops changing.
  const [totalAdded, setTotalAdded] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!path) return

    let cancelled = false
    let backoff = 1000 // start at 1s, doubles on failure, caps at 30s

    async function connect() {
      while (!cancelled) {
        const controller = new AbortController()
        abortRef.current = controller

        try {
          const token = useAuthStore.getState().accessToken
          const headers: Record<string, string> = {
            Accept: 'text/event-stream',
          }
          if (token) {
            headers['Authorization'] = `Bearer ${token}`
          }

          const response = await fetch(`${API_BASE}${path}`, {
            headers,
            signal: controller.signal,
          })

          if (!response.ok) {
            if (response.status === 401) {
              // Token expired — try refresh once, then retry connect
              const { ApiClient } = await import('@/lib/api')
              const refreshed = await ApiClient.refreshTokens()
              if (!refreshed) {
                // Can't recover — stop retrying
                setConnected(false)
                return
              }
            }
            if (response.status === 403) {
              // Not allowed to read this stream: retrying cannot change that.
              setConnected(false)
              return
            }
            throw new Error(`SSE ${response.status}`)
          }

          // Connected successfully — reset backoff
          backoff = 1000
          let accessRevoked = false

          for await (const frame of parseSseStream(response, controller.signal)) {
            if (cancelled) break
            if (frame.event === 'connected') {
              setConnected(true)
              continue
            }
            // The server closes the stream when its session ends. It is not an event for the
            // caller; the reconnect below fails with 401 and stops once the refresh is refused.
            if (frame.event === 'session_ended') continue
            // The user lost access to what this stream shows. The server closes it, and a
            // reconnect would be refused with 403, so stop here.
            if (frame.event === 'access_revoked') {
              accessRevoked = true
              break
            }
            try {
              const parsed = JSON.parse(frame.data) as SseEvent
              setEvents((prev) => [...prev, parsed].slice(-maxEvents))
              setTotalAdded((n) => n + 1)
            } catch {
              // skip malformed
            }
          }

          setConnected(false)
          if (accessRevoked) return

          // Stream ended cleanly (server closed) — reconnect
        } catch (err) {
          if (cancelled || (err instanceof DOMException && err.name === 'AbortError')) {
            return
          }
          setConnected(false)
        }

        if (cancelled) return
        // Wait before reconnecting
        await new Promise((r) => setTimeout(r, backoff))
        backoff = Math.min(backoff * 2, 30_000)
      }
    }

    connect()

    return () => {
      cancelled = true
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [path, maxEvents])

  const clear = useCallback(() => setEvents([]), [])

  return { events, connected, clear, totalAdded }
}

/**
 * Subscribe to a run's SSE event stream.
 * Returns latest events and a connected flag.
 */
export function useRunStream(sessionId: string | null) {
  return useFetchSse(
    sessionId ? `/streams/runs/${sessionId}` : null,
    200,
  )
}

/**
 * Subscribe to a mission's SSE event stream.
 * Returns latest events, a connected flag, and totalAdded (uncapped event count
 * for detecting new events when the ring buffer is full).
 */
export function useMissionStream(missionId: string | null) {
  return useFetchSse(
    missionId ? `/streams/missions/${missionId}` : null,
    1000,
  )
}

/**
 * Subscribe to user notification SSE stream.
 * Calls onNotification for each incoming event.
 *
 * Reuses useFetchSse for connection management — no separate backoff/abort loop.
 */
export function useNotificationStream(
  userId: string | null,
  onNotification: (data: Record<string, unknown>) => void,
) {
  const callbackRef = useRef(onNotification)
  callbackRef.current = onNotification

  const { events, totalAdded } = useFetchSse(
    userId ? `/streams/notifications?user_id=${userId}` : null,
    200,
  )

  const processedRef = useRef(0)
  useEffect(() => {
    if (totalAdded <= processedRef.current) return
    const delta = totalAdded - processedRef.current
    processedRef.current = totalAdded
    events.slice(-delta).forEach((ev) => callbackRef.current(ev.data))
  }, [totalAdded, events])
}
