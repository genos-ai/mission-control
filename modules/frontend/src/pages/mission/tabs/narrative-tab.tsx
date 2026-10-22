/**
 * NarrativeTab — console view showing ALL mission events.
 *
 * On mount, loads historical events from GET /missions/{id}/narrative
 * (execution records, task states, artifacts reconstructed from DB).
 * Then live SSE events arrive via the console store. Both are merged
 * and deduplicated by event_id, then grouped by session.
 *
 * Uses a BLACKLIST approach: everything is shown unless the user
 * explicitly filters it out via toggle controls.
 */

import { useRef, useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Filter, Radio } from 'lucide-react'
import { api } from '@/lib/api'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { DocumentPage } from '@/components/layout/document-page'
import { NarrativeRun } from '@/components/narrative/narrative-run'
import { groupBySession, isRenderable } from '@/components/narrative/narrative-groups'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { FilterChip } from '@/components/ui/filter-chip'
import { Panel } from '@/components/ui/panel'

// ---------------------------------------------------------------------------
// Filter persistence
// ---------------------------------------------------------------------------

const FILTER_STORAGE_KEY = 'mc:narrative-hidden-types'

function loadHiddenTypes(): Set<string> {
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set()
}

function saveHiddenTypes(hidden: Set<string>) {
  localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify([...hidden]))
}

// ---------------------------------------------------------------------------

export default function NarrativeTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [historical, setHistorical] = useState<ConsoleEvent[]>([])
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(loadHiddenTypes)
  const [showFilters, setShowFilters] = useState(false)
  const liveEvents = useConsoleStore((s) => s.events)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load historical events from DB on mount
  useEffect(() => {
    if (!missionId) return
    api.get<{ events: ConsoleEvent[]; count: number }>(`/missions/${missionId}/narrative`)
      .then((data) => setHistorical(data.events))
      .catch(() => {})
  }, [missionId])

  // Merge historical + live, deduplicate by event_id, and count each type for the filter UI
  const seen = new Set<string>()
  const typeCounts = new Map<string, number>()
  const allEvents: ConsoleEvent[] = []
  for (const ev of [...historical, ...liveEvents]) {
    if (!seen.has(ev.event_id)) {
      seen.add(ev.event_id)
      allEvents.push(ev)
      typeCounts.set(ev.event_type, (typeCounts.get(ev.event_type) ?? 0) + 1)
    }
  }

  // Apply blacklist filter
  const events = allEvents.filter((e) => !hiddenTypes.has(e.event_type) && isRenderable(e))
  const groups = groupBySession(allEvents, hiddenTypes)

  const eventTypes = [...typeCounts.keys()].sort()

  const toggleType = useCallback((type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      saveHiddenTypes(next)
      return next
    })
  }, [])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events.length, autoScroll])

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <DocumentPage className="max-w-[820px] gap-4">
        {/* Pinned so the filter stays reachable while auto-scroll holds the page at the bottom. */}
        <div className="sticky top-0 z-10 flex flex-col gap-3 bg-well pb-2 pt-3">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h1 className="text-lg font-semibold">Narrative</h1>
              <p className="text-sm text-subtle">The mission&apos;s story so far, in plain language</p>
            </div>
            <span className="pt-1.5 font-mono text-2xs text-subtle">
              {events.length} event{events.length !== 1 ? 's' : ''}
            </span>
            <Button
              variant={showFilters ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={showFilters}
              onClick={() => setShowFilters((v) => !v)}
            >
              <Filter className="h-3 w-3" />
              Filters
              {hiddenTypes.size > 0 && <Badge>{hiddenTypes.size} hidden</Badge>}
            </Button>
          </div>

          {showFilters && eventTypes.length > 0 && (
            <Panel
              role="group"
              aria-label="Event types shown"
              className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto px-4 py-3"
            >
              {eventTypes.map((type) => (
                <FilterChip
                  key={type}
                  active={!hiddenTypes.has(type)}
                  count={typeCounts.get(type)}
                  onClick={() => toggleType(type)}
                >
                  {type}
                </FilterChip>
              ))}
            </Panel>
          )}
        </div>

        {events.length === 0 && (
          allEvents.some((e) => hiddenTypes.has(e.event_type)) ? (
            <EmptyState
              icon={<Radio className="h-4 w-4" />}
              title="All events are filtered out"
              description="Adjust filters above."
            />
          ) : (
            <EmptyState
              icon={<Radio className="h-4 w-4" />}
              title="No events yet"
              description="Events will appear here during a run."
            />
          )
        )}
        {groups.map((group) => (
          <NarrativeRun key={group.key} group={group} />
        ))}
      </DocumentPage>
    </div>
  )
}
