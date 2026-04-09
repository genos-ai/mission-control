import { createContext, useContext } from 'react'

export interface SseEvent {
  event_type: string
  data: Record<string, unknown>
}

export interface MissionStreamValue {
  events: SseEvent[]
  connected: boolean
}

/**
 * Shared SSE stream from MissionWorkspace down to child panels.
 * Lets ConsolePage consume the stream without opening a second connection.
 * Children that are rendered outside MissionWorkspace (legacy tab routes)
 * will get null and open their own connection as before.
 */
export const MissionStreamContext = createContext<MissionStreamValue | null>(null)

export function useMissionStreamContext(): MissionStreamValue | null {
  return useContext(MissionStreamContext)
}
