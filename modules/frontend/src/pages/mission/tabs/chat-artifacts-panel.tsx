import { useMemo, useRef, useEffect, useState } from 'react'
import { PanelRightClose, AlertTriangle, Zap, Inbox } from 'lucide-react'

import { Panel } from '@/components/ui/panel'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { useResizable } from '@/hooks/use-resizable'
import { formatUtc } from '@/lib/format-date'
import { cn } from '@/lib/cn'

const MIN_RESULT_LENGTH = 200

export function ToolOutputPanel({
  activeAgent,
  activeSessionId,
  onClose,
}: {
  activeAgent: string
  activeSessionId: string | null
  onClose: () => void
}) {
  const { width, onMouseDown } = useResizable(288)
  const scrollRef = useRef<HTMLDivElement>(null)

  const events = useConsoleStore((s) => s.events)

  const toolResults = useMemo(() => {
    return events.filter((e) => {
      if (e.event_type !== 'agent.tool.returned') return false

      const agentId = String(e.data.agent_id ?? e.source ?? '')
      if (agentId !== activeAgent) return false

      // If we have a session, scope to it; otherwise accept all
      if (activeSessionId) {
        const sid = String(e.data.session_id ?? '')
        if (sid && sid !== activeSessionId) return false
      }

      const status = String(e.data.status ?? '')
      const result = String(e.data.result ?? '')

      return status === 'error' || result.length > MIN_RESULT_LENGTH
    })
  }, [events, activeAgent, activeSessionId])

  // Scroll to bottom when new results arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [toolResults.length])

  return (
    <Panel className="relative hidden shrink-0 flex-col min-[1200px]:flex" style={{ width }}>
      {/* Resize handle: invisible until hovered. */}
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 z-10 h-full w-1 cursor-col-resize transition-colors hover:bg-brand/30"
      />

      <div className="flex h-12 shrink-0 items-center gap-2 px-4 pt-1">
        <span className="text-base font-medium">Outputs</span>
        {toolResults.length > 0 && <span className="font-mono text-xs text-subtle">{toolResults.length}</span>}
        <button
          onClick={onClose}
          aria-label="Collapse outputs"
          className="ml-auto rounded-chip p-1 text-subtle transition-colors duration-150 hover:bg-raised hover:text-foreground"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-2.5 pb-3">
        {toolResults.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-5 py-8">
            <Inbox className="h-5 w-5 text-faint" />
            <p className="text-center text-xs text-subtle">Tool outputs will appear here during a run.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {toolResults.map((e) => (
              <ToolResultCard key={e.event_id} event={e} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  )
}

function ToolResultCard({ event }: { event: ConsoleEvent }) {
  const [expanded, setExpanded] = useState(false)
  const d = event.data
  const tool = String(d.tool_name ?? '')
  const result = String(d.result ?? '')
  const isError = String(d.status ?? '') === 'error'
  const Icon = isError ? AlertTriangle : Zap

  return (
    <div className="overflow-hidden rounded-card bg-raised">
      <button
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <Icon className={cn('h-3 w-3 shrink-0', isError ? 'text-danger' : 'text-warning')} />
        <span className={cn('min-w-0 flex-1 truncate font-mono text-xs', isError && 'text-danger')}>{tool}</span>
        <span className="shrink-0 font-mono text-2xs text-subtle">{formatUtc(event.timestamp)}</span>
      </button>
      <pre
        className={cn(
          'whitespace-pre-wrap px-3 pb-2.5 font-mono text-2xs leading-[17px] text-muted-foreground [overflow-wrap:anywhere]',
          expanded ? 'max-h-64 overflow-y-auto' : 'line-clamp-4',
        )}
      >
        {result}
      </pre>
    </div>
  )
}
