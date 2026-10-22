import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Terminal } from 'lucide-react'
import { ConsoleRow } from '@/components/console/console-row'
import { ConsoleToolbar } from '@/components/console/console-toolbar'
import { EmptyState } from '@/components/ui/empty-state'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { useConsoleHistory } from '@/hooks/use-console'
import { useMissionStream } from '@/hooks/use-sse'
import { useMissionStreamContext } from '@/context/mission-stream'
import { useTeam } from '@/hooks/use-team'
import { categorize } from '@/lib/console-event'
import {
  useConsoleStore,
  selectFilteredEvents,
  type ConsoleEvent,
} from '@/stores/console'

export default function ConsolePage() {
  const { id: missionId } = useParams<{ id: string }>()

  const { data: history, isLoading: historyLoading } =
    useConsoleHistory(missionId)

  // Use shared stream from MissionWorkspace when available (avoids a second SSE connection).
  // Falls back to its own connection when rendered as a standalone legacy tab page.
  const streamCtx = useMissionStreamContext()
  const ownStream = useMissionStream(streamCtx ? null : (missionId ?? null))
  const { events: sseEvents, connected } = streamCtx ?? ownStream

  const { data: teamMembers } = useTeam(missionId)

  const addEvents = useConsoleStore((s) => s.addEvents)
  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)

  // Reset store when mission changes (only in standalone mode — workspace handles its own reset)
  const storeMissionId = useRef<string | null>(null)
  const historyLoaded = useRef(false)
  useEffect(() => {
    if (!streamCtx && missionId && missionId !== storeMissionId.current) {
      storeMissionId.current = missionId
      historyLoaded.current = false
      useConsoleStore.getState().clear()
    }
  }, [missionId, streamCtx])

  // Load history into store
  useEffect(() => {
    if (history && !historyLoaded.current) {
      historyLoaded.current = true
      addEvents([...history].reverse())
    }
  }, [history, addEvents])

  useEffect(() => {
    // Only update connected state in standalone mode — workspace already does this
    if (!streamCtx) setConnected(connected)
  }, [connected, setConnected, streamCtx])

  // Forward SSE events to store — skip when workspace already handles routing
  const processedCount = useRef(0)
  useEffect(() => {
    if (streamCtx) return  // workspace owns event routing; console store already populated
    if (sseEvents.length > processedCount.current) {
      const newEvents = sseEvents.slice(processedCount.current)
      processedCount.current = sseEvents.length
      newEvents.forEach((ev) => {
        const d = ev.data as Record<string, unknown>
        addEvent({
          event_id: String(d.event_id ?? crypto.randomUUID()),
          event_type: ev.event_type,
          category: (d.category as ConsoleEvent['category']) ?? categorize(ev.event_type),
          timestamp: String(d.timestamp ?? new Date().toISOString()),
          source: String(d.agent_id ?? d.source ?? ''),
          data: d,
        })
      })
    }
  }, [sseEvents.length, streamCtx]) // eslint-disable-line react-hooks/exhaustive-deps

  if (historyLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col px-2 pb-2">
      <Panel className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <ConsoleToolbar teamMembers={teamMembers} />
        <Timeline />
      </Panel>
    </div>
  )
}

function Timeline() {
  const categoryTab = useConsoleStore((s) => s.categoryTab)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const filtered = useConsoleStore((s) =>
    categoryTab === 'all'
      ? selectFilteredEvents(s, null)
      : selectFilteredEvents(s, categoryTab),
  )
  const eventCount = useConsoleStore((s) => s.events.length)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll) {
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [filtered.length, autoScroll])

  return (
    <div ref={scrollRef} className="mx-2 mb-2 min-h-0 flex-1 overflow-y-auto rounded-card bg-well/50 p-1">
      {filtered.length === 0 && (
        <EmptyState
          icon={<Terminal className="h-4 w-4" />}
          title={eventCount === 0 ? 'No events yet' : 'No events match these filters'}
          description={
            eventCount === 0
              ? 'Events appear here as the mission runs.'
              : 'Change the category, agent or Errors filter to see more.'
          }
        />
      )}
      {filtered.map((ev) => (
        <ConsoleRow key={ev.event_id} event={ev} />
      ))}
    </div>
  )
}
