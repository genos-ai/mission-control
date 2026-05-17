import { useEffect, useRef, useCallback, useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { API_BASE } from '@/lib/constants'

interface SseEvent {
  event_type: string
  data: Record<string, unknown>
}

/**
 * Parse an SSE text stream from a fetch Response.
 *
 * Yields parsed events as they arrive. Handles the `event:` and `data:`
 * fields per the SSE spec. Reconnection is handled by the caller.
 */
async function* parseSseStream(
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
            throw new Error(`SSE ${response.status}`)
          }

          // Connected successfully — reset backoff
          backoff = 1000

          for await (const frame of parseSseStream(response, controller.signal)) {
            if (cancelled) break
            if (frame.event === 'connected') {
              setConnected(true)
              continue
            }
            try {
              const parsed = JSON.parse(frame.data) as SseEvent
              setEvents((prev) => [...prev, parsed].slice(-maxEvents))
            } catch {
              // skip malformed
            }
          }

          // Stream ended cleanly (server closed) — reconnect
          setConnected(false)
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

  return { events, connected, clear }
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
 * Returns latest events and a connected flag.
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
 */
export function useNotificationStream(
  userId: string | null,
  onNotification: (data: Record<string, unknown>) => void,
) {
  const callbackRef = useRef(onNotification)
  callbackRef.current = onNotification
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!userId) return

    let cancelled = false
    let backoff = 1000

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

          const response = await fetch(
            `${API_BASE}/streams/notifications?user_id=${userId}`,
            { headers, signal: controller.signal },
          )

          if (!response.ok) {
            if (response.status === 401) {
              const { ApiClient } = await import('@/lib/api')
              const refreshed = await ApiClient.refreshTokens()
              if (!refreshed) return
            }
            throw new Error(`SSE ${response.status}`)
          }

          backoff = 1000

          for await (const frame of parseSseStream(response, controller.signal)) {
            if (cancelled) break
            try {
              const data = JSON.parse(frame.data)
              callbackRef.current(data)
            } catch {
              // skip
            }
          }
        } catch (err) {
          if (cancelled || (err instanceof DOMException && err.name === 'AbortError')) {
            return
          }
        }

        if (cancelled) return
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
  }, [userId])
}
