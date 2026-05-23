import { useMemo, useRef, useEffect } from 'react'
import { ChevronRight, AlertTriangle, Zap, Inbox } from 'lucide-react'
import { useConsoleStore } from '@/stores/console'
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
  const { width, onMouseDown } = useResizable(300)
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

  const agentShort = activeAgent.endsWith('.agent')
    ? activeAgent.slice(0, -6)
    : activeAgent

  return (
    <div className="relative flex shrink-0 flex-col border-l" style={{ width }}>
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/20 transition-colors z-10"
      />

      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium">Outputs</span>
          <span className="text-[10px] text-muted-foreground/50 truncate max-w-[100px]">
            {agentShort}
          </span>
          {toolResults.length > 0 && (
            <span className="text-[10px] text-muted-foreground/50">
              · {toolResults.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Content */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {toolResults.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-5 py-8">
            <Inbox className="h-5 w-5 text-muted-foreground/20" />
            <p className="text-center text-[11px] text-muted-foreground/40">
              Tool outputs will appear here during a run.
            </p>
          </div>
        ) : (
          <div className="space-y-px p-2">
            {toolResults.map((e) => (
              <ToolResultCard key={e.event_id} event={e} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ToolResultCard({ event }: { event: ReturnType<typeof useConsoleStore.getState>['events'][number] }) {
  const d = event.data
  const tool = String(d.tool_name ?? '')
  const status = String(d.status ?? '')
  const result = String(d.result ?? '')
  const isError = status === 'error'

  return (
    <details className={cn(
      'group rounded border p-2 text-xs',
      isError
        ? 'border-destructive/20 bg-destructive/5'
        : 'border-border/50 bg-muted/20',
    )}>
      <summary className="flex cursor-pointer list-none items-start gap-1.5">
        {isError
          ? <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
          : <Zap className="mt-0.5 h-3 w-3 shrink-0 text-amber-400/70" />
        }
        <div className="min-w-0 flex-1">
          <p className={cn('font-medium font-mono leading-snug', isError ? 'text-destructive' : '')}>
            {tool}
          </p>
          <p className="text-[10px] text-muted-foreground/50">
            {formatUtc(event.timestamp)}
          </p>
        </div>
      </summary>
      <div className="mt-2 border-t border-border/30 pt-2">
        <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground leading-relaxed">
          {result}
        </pre>
      </div>
    </details>
  )
}
