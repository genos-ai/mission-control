import { useEffect, useRef, useCallback, useState } from 'react'
import { api } from '@/lib/api'

interface SseEvent {
  event_type: string
  data: Record<string, unknown>
}

/**
 * Subscribe to a run's SSE event stream.
 * Returns latest events and a connected flag.
 */
export function useRunStream(sessionId: string | null) {
  const [events, setEvents] = useState<SseEvent[]>([])
  const [connected, setConnected] = useState(false)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!sessionId) return

    const source = api.sse(`/streams/runs/${sessionId}`)
    sourceRef.current = source

    source.addEventListener('connected', () => {
      setConnected(true)
    })

    source.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as SseEvent
        setEvents((prev) => [...prev, parsed].slice(-200))
      } catch {
        // skip malformed
      }
    }

    source.onerror = () => {
      setConnected(false)
    }

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [sessionId])

  const clear = useCallback(() => setEvents([]), [])

  return { events, connected, clear }
}

/**
 * Subscribe to a mission's SSE event stream.
 * Returns latest events and a connected flag.
 */
export function useMissionStream(missionId: string | null) {
  const [events, setEvents] = useState<SseEvent[]>([])
  const [connected, setConnected] = useState(false)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!missionId) return

    const source = api.sse(`/streams/missions/${missionId}`)
    sourceRef.current = source

    source.addEventListener('connected', () => {
      setConnected(true)
    })

    source.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as SseEvent
        setEvents((prev) => [...prev, parsed].slice(-1000))
      } catch {
        // skip malformed
      }
    }

    source.onerror = () => {
      setConnected(false)
    }

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [missionId])

  const clear = useCallback(() => setEvents([]), [])

  return { events, connected, clear }
}

/**
 * Subscribe to user notification SSE stream.
 * Calls onNotification for each incoming event.
 */
export function useNotificationStream(
  userId: string | null,
  onNotification: (data: Record<string, unknown>) => void,
) {
  const sourceRef = useRef<EventSource | null>(null)
  const callbackRef = useRef(onNotification)
  callbackRef.current = onNotification

  useEffect(() => {
    if (!userId) return

    const source = api.sse(`/streams/notifications?user_id=${userId}`)
    sourceRef.current = source

    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        callbackRef.current(data)
      } catch {
        // skip
      }
    }

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [userId])
}
