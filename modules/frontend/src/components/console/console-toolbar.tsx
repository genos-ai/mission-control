import { AlertCircle, Pause, Play, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { FilterChip } from '@/components/ui/filter-chip'
import { Segmented } from '@/components/ui/segmented'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { TONE_DOT } from '@/lib/tone-class'
import { selectFilteredEvents, useConsoleStore, type ConsoleEvent } from '@/stores/console'

type CategoryTab = 'all' | ConsoleEvent['category']

const CATEGORY_OPTIONS: { value: CategoryTab; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'execution', label: 'Execution' },
  { value: 'chat', label: 'Chat' },
  { value: 'system', label: 'System' },
]

interface TeamMemberOption {
  agent_catalog_id: string
  agent?: { agent_name: string } | null
}

/** How many events each category tab would show with the agent and error filters applied. */
function useCategoryCounts(): Record<CategoryTab, number> {
  const all = useConsoleStore((s) => selectFilteredEvents(s, null).length)
  const execution = useConsoleStore((s) => selectFilteredEvents(s, 'execution').length)
  const chat = useConsoleStore((s) => selectFilteredEvents(s, 'chat').length)
  const system = useConsoleStore((s) => selectFilteredEvents(s, 'system').length)
  return { all, execution, chat, system }
}

export function ConsoleToolbar({ teamMembers }: { teamMembers?: TeamMemberOption[] }) {
  const categoryTab = useConsoleStore((s) => s.categoryTab)
  const agentFilter = useConsoleStore((s) => s.agentFilter)
  const errorsOnly = useConsoleStore((s) => s.errorsOnly)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const connected = useConsoleStore((s) => s.connected)
  const eventCount = useConsoleStore((s) => s.events.length)
  // Counted with the store's own Errors filter so the pill and the chip agree.
  const errorCount = useConsoleStore(
    (s) => selectFilteredEvents({ ...s, agentFilter: null, errorsOnly: true }, null).length,
  )
  const setCategoryTab = useConsoleStore((s) => s.setCategoryTab)
  const setAgentFilter = useConsoleStore((s) => s.setAgentFilter)
  const setErrorsOnly = useConsoleStore((s) => s.setErrorsOnly)
  const toggleAutoScroll = useConsoleStore((s) => s.toggleAutoScroll)
  const clear = useConsoleStore((s) => s.clear)
  const counts = useCategoryCounts()
  const shown = counts[categoryTab]

  return (
    <div className="flex flex-wrap items-center gap-2.5 px-3 py-2.5">
      <Segmented
        label="Event category"
        value={categoryTab}
        onChange={setCategoryTab}
        options={CATEGORY_OPTIONS.map((o) => ({ ...o, count: counts[o.value] }))}
      />

      <select
        aria-label="Agent"
        value={agentFilter ?? ''}
        onChange={(e) => setAgentFilter(e.target.value || null)}
        className="h-7 max-w-[200px] rounded-control border border-panel-border bg-raised px-2 text-xs text-muted-foreground outline-none transition-colors hover:text-foreground focus:border-brand/60"
      >
        <option value="">All agents</option>
        {teamMembers?.map((m) => (
          <option key={m.agent_catalog_id} value={m.agent?.agent_name ?? m.agent_catalog_id}>
            {m.agent?.agent_name ?? m.agent_catalog_id}
          </option>
        ))}
      </select>

      <FilterChip active={errorsOnly} onClick={() => setErrorsOnly(!errorsOnly)}>
        <AlertCircle className="h-3 w-3" />
        Errors
      </FilterChip>

      <div className="ml-auto flex flex-wrap items-center gap-2.5">
        {errorCount > 0 && (
          <StatusPill tone="danger" dot={false}>
            <AlertCircle className="h-3 w-3" />
            {errorCount} {errorCount === 1 ? 'error' : 'errors'}
          </StatusPill>
        )}
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className={cn('h-1.5 w-1.5 rounded-full', connected ? TONE_DOT.success : TONE_DOT.neutral)} />
          {connected ? 'Live' : 'Disconnected'}
          <span aria-hidden="true">·</span>
          <span className="font-mono text-subtle">
            {shown === eventCount ? `${eventCount} events` : `${shown} / ${eventCount} events`}
          </span>
        </span>
        <Button variant="ghost" size="sm" onClick={clear}>
          <Trash2 className="h-3 w-3" />
          Clear
        </Button>
        <Button
          variant={autoScroll ? 'secondary' : 'ghost'}
          size="sm"
          aria-pressed={autoScroll}
          title={autoScroll ? 'Auto-scroll is on' : 'Auto-scroll is paused'}
          onClick={toggleAutoScroll}
        >
          {autoScroll ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          Auto
        </Button>
      </div>
    </div>
  )
}
