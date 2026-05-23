import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCatalogAgent } from '@/hooks/use-catalog'
import { SlashCommandPopover } from '@/components/chat/slash-command-popover'
import {
  Bot,
  Brain,
  Loader2,
  Send,
  AlertTriangle,
  User,
  Package,
  Zap,
  Activity,
  Search,
  Info,
} from 'lucide-react'
import { formatUtc } from '@/lib/format-date'
import { useBackgroundTasks } from '@/hooks/use-executions'
import toast from 'react-hot-toast'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useMessages, sessionKeys } from '@/hooks/use-sessions'
import { parseSseStream } from '@/hooks/use-sse'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { queryClient } from '@/lib/query-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { API_BASE } from '@/lib/constants'
import type { SessionMessage } from '@/types'
import { eventLabel } from '@/lib/event-utils'
import { CHAT_HIDDEN_EVENT_TYPES, type TimelineEntry } from './chat-constants'

export function Conversation({ sessionId, missionId, targetAgent }: { sessionId: string; missionId: string; targetAgent?: string }) {
  const { data: history, isLoading } = useMessages(sessionId, targetAgent)
  const { user } = useAuthStore()
  const { activeCount: bgTaskCount, activeTasks: bgTasks } = useBackgroundTasks(missionId)
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingThinking, setStreamingThinking] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Slash-command autocomplete
  // slashFilter === null  → popover closed
  // slashFilter === ''    → popover open, show all tools
  // slashFilter === 'run' → popover open, filtered
  const [slashFilter, setSlashFilter] = useState<string | null>(null)
  const [slashIndex, setSlashIndex] = useState(0)
  const { data: agentDetail } = useCatalogAgent(targetAgent)
  const agentTools: string[] = agentDetail?.tools ?? []
  // Pre-filtered tool list — single computation point used by both the
  // popover and the keyboard handler so they always agree on what's visible.
  const filteredTools = useMemo(() => {
    if (slashFilter === null) return []
    if (!slashFilter) return agentTools
    const q = slashFilter.toLowerCase()
    return agentTools.filter((t) => t.toLowerCase().includes(q))
  }, [slashFilter, agentTools])

  // Historical narrative events from DB — cached per mission, filtered client-side by sessionId
  const { data: narrativeData } = useQuery({
    queryKey: ['narrative', missionId],
    queryFn: () => api.get<{ events: ConsoleEvent[]; count: number }>(`/missions/${missionId}/narrative`),
    enabled: !!missionId,
    staleTime: 30_000,
  })
  const historicalEvents = useMemo(() => {
    if (!narrativeData) return []
    return narrativeData.events.filter(
      (e) => !CHAT_HIDDEN_EVENT_TYPES.has(e.event_type) && e.data.session_id === sessionId,
    )
  }, [narrativeData, sessionId])

  // Live narrative events from SSE
  const liveEvents = useConsoleStore((s) =>
    s.events.filter((e) => !CHAT_HIDDEN_EVENT_TYPES.has(e.event_type) && e.data.session_id === sessionId),
  )

  useEffect(() => {
    setMessages([])
    setStreamingContent('')
    setStreamingThinking('')
    setSending(false)
    setSlashFilter(null)
    setSlashIndex(0)
    abortRef.current?.abort()
    abortRef.current = null
  }, [sessionId])

  useEffect(() => { if (history) setMessages(history) }, [history])
  useEffect(() => () => { abortRef.current?.abort() }, [])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, streamingContent, streamingThinking, liveEvents.length])

  const sendMessage = useCallback(async () => {
    const content = input.trim()
    if (!content || sending) return
    setInput('')
    setSending(true)
    setStreamingContent('')
    setStreamingThinking('')

    setMessages((prev) => [
      ...prev,
      {
        id: `temp-${Date.now()}`, session_id: sessionId, role: 'user', content,
        sender_id: user?.id ?? null, model: null, input_tokens: null,
        output_tokens: null, cost_usd: null, tool_name: null, tool_call_id: null,
        thinking: null, target_agent: targetAgent ?? null,
        status: 'complete' as const, created_at: new Date().toISOString(),
        updated_at: null,
      },
    ])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = useAuthStore.getState().accessToken
      const response = await fetch(
        `${API_BASE}/sessions/${sessionId}/messages?mission_id=${missionId}${targetAgent ? `&target_agent=${encodeURIComponent(targetAgent)}` : ''}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ content, role: 'user', sender_id: user?.id }),
          signal: controller.signal,
        },
      )
      if (!response.ok) throw new Error('Failed to send message')

      let accumulated = ''

      for await (const frame of parseSseStream(response, controller.signal)) {
        if (!frame.data || frame.data === '{}') continue
        try {
          const ev = JSON.parse(frame.data)
          if (ev.event_type === 'agent.response.chunk') {
            if (ev.metadata?.thinking) setStreamingThinking((p) => p + (ev.content ?? ''))
            else { accumulated += ev.content ?? ''; setStreamingContent(accumulated) }
          } else if (ev.event_type === 'agent.response.complete') {
            setMessages((p) => [
              ...p,
              {
                id: `resp-${Date.now()}`, session_id: sessionId,
                role: 'assistant' as const,
                content: ev.full_content ?? accumulated,
                sender_id: ev.agent_id ?? null, model: ev.model ?? null,
                input_tokens: ev.input_tokens ?? null, output_tokens: ev.output_tokens ?? null,
                cost_usd: ev.cost_usd ?? null, tool_name: null, tool_call_id: null,
                thinking: ev.metadata?.thinking ?? null, target_agent: targetAgent ?? null,
                status: (ev.metadata?.error ? 'failed' : 'complete') as 'failed' | 'complete',
                created_at: new Date().toISOString(), updated_at: null,
              },
            ])
            accumulated = ''
            setStreamingContent('')
            setStreamingThinking('')
          }
        } catch { /* skip malformed SSE frame */ }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      toast.error(err instanceof Error ? err.message : 'Send failed')
    } finally {
      abortRef.current = null
      setSending(false)
      queryClient.invalidateQueries({ queryKey: sessionKeys.messages(sessionId, targetAgent) })
    }
  }, [input, sending, sessionId, missionId, targetAgent, user?.id])

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setInput(val)
    // Open slash-command popover when text starts with / and has no space yet
    // (once the user types a space they are typing arguments, not a command name)
    if (val.startsWith('/') && !val.includes(' ') && agentTools.length > 0) {
      setSlashFilter(val.slice(1))
      setSlashIndex(0)
    } else {
      setSlashFilter(null)
    }
  }, [agentTools])

  const handleSlashSelect = useCallback((tool: string) => {
    setInput(`/${tool} `)
    setSlashFilter(null)
    setSlashIndex(0)
    textareaRef.current?.focus()
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Slash-command popover navigation takes priority when open.
    // filteredTools is the single source of truth — same list the popover renders.
    if (slashFilter !== null) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex((i) => Math.min(i + 1, filteredTools.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        if (filteredTools[slashIndex]) handleSlashSelect(filteredTools[slashIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashFilter(null)
        return
      }
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendMessage() }
  }, [slashFilter, filteredTools, slashIndex, handleSlashSelect, sendMessage])

  // Build unified timeline: messages + narrative events, sorted by timestamp
  // Must be above the isLoading return — hooks can't be after early returns.
  const timeline = useMemo(() => {
    const entries: TimelineEntry[] = []

    for (const msg of messages) {
      if (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'error') {
        entries.push({ kind: 'message', ts: msg.created_at, data: msg })
      }
    }

    const seen = new Set<string>()
    for (const ev of [...historicalEvents, ...liveEvents]) {
      if (!seen.has(ev.event_id)) {
        seen.add(ev.event_id)
        entries.push({ kind: 'event', ts: ev.timestamp, data: ev })
      }
    }

    entries.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())
    return entries
  }, [messages, historicalEvents, liveEvents])

  if (isLoading) return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  )

  return (
    <>
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {timeline.map((entry) =>
          entry.kind === 'message'
            ? <MessageBubble key={entry.data.id} message={entry.data} />
            : <InlineNarrativeRow key={entry.data.event_id} event={entry.data} />,
        )}

        {(streamingThinking || streamingContent) && (
          <div className="flex gap-3">
            <Bot className="mt-1 h-5 w-5 shrink-0 text-primary" />
            <div className="flex-1 space-y-2">
              {streamingThinking && (
                <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3">
                  <div className="mb-1 flex items-center gap-1.5">
                    <Brain className="h-3 w-3 text-purple-400" />
                    <span className="text-xs font-medium text-purple-400">Thinking</span>
                    {!streamingContent && <Loader2 className="h-3 w-3 animate-spin text-purple-400" />}
                  </div>
                  <p className="whitespace-pre-wrap font-mono text-xs text-muted-foreground">
                    {streamingThinking.slice(-800)}
                  </p>
                </div>
              )}
              {streamingContent && (
                <div className="rounded-lg bg-muted/50 p-3">
                  <MarkdownRenderer content={streamingContent} className="text-[13px]" />
                  <Loader2 className="mt-1 h-3 w-3 animate-spin text-muted-foreground" />
                </div>
              )}
            </div>
          </div>
        )}

        {sending && !streamingContent && !streamingThinking && (
          <div className="flex gap-3">
            <Bot className="mt-1 h-5 w-5 text-primary" />
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />Thinking...
            </div>
          </div>
        )}

        {!sending && bgTaskCount > 0 && (
          <div className="flex gap-3">
            <Bot className="mt-1 h-5 w-5 text-primary/50" />
            <div className="flex items-center gap-2 rounded-lg border border-primary/10 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin text-primary/60" />
              <span>Working in background: {bgTasks.map((t) => t.task_type?.replace('_', ' ')).join(', ')}</span>
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t p-3">
        <div className="relative flex gap-2">
          {filteredTools.length > 0 && (
            <SlashCommandPopover
              tools={filteredTools}
              activeIndex={slashIndex}
              onSelect={handleSlashSelect}
            />
          )}
          <Textarea
            ref={textareaRef}
            value={input} onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Send a message… (Cmd+Enter or type / for commands)"
            rows={2} className="resize-none text-sm" disabled={sending}
          />
          <Button size="icon" onClick={sendMessage}
            disabled={!input.trim() || sending} className="h-auto">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">Cmd+Enter to send · / for commands</p>
      </div>
    </>
  )
}

export function InlineNarrativeRow({ event }: { event: ConsoleEvent }) {
  const d = event.data
  // Backend timestamps are UTC but may lack the Z suffix.
  // Append Z if missing so the browser converts to local time correctly.
  const raw = event.timestamp.endsWith('Z') || event.timestamp.includes('+')
    ? event.timestamp
    : event.timestamp + 'Z'
  const ts = new Date(raw).toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  })

  if (event.event_type === 'agent.thinking.started') {
    const agent = String(d.agent_id ?? event.source ?? '')
    const short = agent.endsWith('.agent') ? agent.slice(0, -6) : agent
    return (
      <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/60">
        <Brain className="h-3 w-3 text-purple-400" />
        <span>{short} is thinking…</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'agent.tool.called') {
    const agent = String(d.agent_id ?? event.source ?? '')
    const short = agent.endsWith('.agent') ? agent.slice(0, -6) : agent
    const tool = String(d.tool_name ?? '')
    return (
      <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/60">
        <Zap className="h-3 w-3 text-amber-400" />
        <span>{short}</span>
        <span className="text-muted-foreground/30">→</span>
        <span className="font-medium text-amber-400/80">{tool}</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'agent.tool.returned') {
    const tool = String(d.tool_name ?? '')
    const status = String(d.status ?? 'success')
    const result = String(d.result ?? '')
    const isError = status === 'error'
    if (!isError) return null // only show errors — success is noise
    return (
      <div className="mx-8 flex items-start gap-2 rounded border border-destructive/20 bg-destructive/5 px-3 py-1.5 text-xs">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-destructive">{tool} failed</span>
          <p className="mt-0.5 truncate text-muted-foreground">{result}</p>
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.started') {
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-blue-500/5 px-3 py-1.5 text-xs">
        <Activity className="h-3.5 w-3.5 shrink-0 text-blue-400" />
        <span className="font-medium">Starting</span>
        <span className="text-muted-foreground">{String(d.step_name ?? d.step_id ?? '')}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.completed') {
    const status = String(d.status ?? 'success')
    const ok = status === 'success'
    const cost = d.cost_usd != null ? `$${Number(d.cost_usd).toFixed(4)}` : ''
    return (
      <div className={cn(
        'mx-8 flex items-center gap-2 rounded px-3 py-1.5 text-xs',
        ok ? 'bg-emerald-500/5' : 'bg-destructive/5',
      )}>
        <Activity className={cn('h-3.5 w-3.5 shrink-0', ok ? 'text-emerald-400' : 'text-destructive')} />
        <span className="font-medium">{ok ? 'Completed' : 'Failed'}</span>
        <span className="text-muted-foreground">{String(d.step_id ?? '')}</span>
        {cost && <span className="text-muted-foreground/70">{cost}</span>}
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'system.execution.created') {
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        <Activity className="h-3 w-3 shrink-0 text-blue-400" />
        <span className="font-medium">Run started</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'system.execution.completed') {
    const status = String(d.status ?? '')
    const cost = d.total_cost_usd != null ? `$${Number(d.total_cost_usd).toFixed(4)}` : ''
    const dur = d.duration_seconds != null ? `${Number(d.duration_seconds).toFixed(1)}s` : ''
    const ok = status === 'completed'
    return (
      <div className={cn(
        'mx-8 flex items-center gap-2 rounded px-3 py-1.5 text-xs',
        ok ? 'bg-emerald-500/5 text-emerald-300' : 'bg-destructive/5 text-destructive',
      )}>
        <Activity className="h-3 w-3 shrink-0" />
        <span className="font-medium">Run {status}</span>
        {cost && <span>{cost}</span>}
        {dur && <span>{dur}</span>}
        <span className="ml-auto text-[10px] tabular-nums opacity-60">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'mission.artifact.found') {
    const title = String(d.title ?? 'Artifact')
    const artifactType = String(d.artifact_type ?? 'report')
    return (
      <div className="mx-8 flex items-center gap-2 rounded border border-violet-500/20 bg-violet-500/5 px-3 py-1.5 text-xs">
        <Package className="h-3.5 w-3.5 shrink-0 text-violet-400" />
        <span className="font-medium">{title}</span>
        <Badge variant="outline" className="h-4 text-[9px]">{artifactType}</Badge>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  // ── Research events ──────────────────────────────────────────────────

  if (event.event_type === 'research.started') {
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-sky-500/5 px-3 py-1.5 text-xs">
        <Search className="h-3.5 w-3.5 shrink-0 text-sky-400" />
        <span className="font-medium text-sky-300">Research started</span>
        <span className="truncate text-muted-foreground">{String(d.query ?? '')}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.decomposed') {
    const count = Number(d.sub_question_count ?? 0)
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-sky-500/5 px-3 py-1.5 text-xs">
        <Search className="h-3.5 w-3.5 shrink-0 text-sky-400" />
        <span className="font-medium">Decomposed into {count} sub-questions</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.subquestion.updated') {
    const status = String(d.status ?? '')
    const text = String(d.text ?? '')
    const isSearching = status === 'searching'
    const isCovered = status === 'covered'
    return (
      <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/60">
        <Search className={cn('h-3 w-3', isSearching ? 'text-sky-400 animate-pulse' : isCovered ? 'text-emerald-400' : 'text-muted-foreground/40')} />
        <span className="truncate">{text}</span>
        <Badge variant="outline" className="h-4 shrink-0 text-[9px]">{status}</Badge>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.search.completed') {
    const sources = Number(d.sources_found ?? 0)
    const findings = Number(d.findings_count ?? 0)
    return (
      <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/60">
        <Search className="h-3 w-3 text-sky-400" />
        <span>Search round complete</span>
        <span className="text-muted-foreground/40">·</span>
        <span>{sources} sources, {findings} findings</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.coverage.updated') {
    const ratio = d.coverage_ratio != null ? `${(Number(d.coverage_ratio) * 100).toFixed(0)}%` : ''
    return (
      <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/60">
        <Search className="h-3 w-3 text-sky-400" />
        <span>Coverage updated</span>
        {ratio && <span className="font-medium text-sky-300">{ratio}</span>}
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.synthesizing') {
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-sky-500/5 px-3 py-1.5 text-xs">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-sky-400" />
        <span className="font-medium text-sky-300">Synthesizing research report…</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.completed') {
    const findings = Number(d.total_findings ?? 0)
    const cost = d.total_cost_usd != null ? `$${Number(d.total_cost_usd).toFixed(4)}` : ''
    return (
      <div className="mx-8 flex items-center gap-2 rounded bg-emerald-500/5 px-3 py-1.5 text-xs">
        <Search className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
        <span className="font-medium text-emerald-300">Research complete</span>
        <span className="text-muted-foreground">{findings} findings</span>
        {cost && <span className="text-muted-foreground">{cost}</span>}
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'research.failed') {
    return (
      <div className="mx-8 flex items-start gap-2 rounded border border-destructive/20 bg-destructive/5 px-3 py-1.5 text-xs">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-destructive">Research failed</span>
          <p className="mt-0.5 truncate text-muted-foreground">{String(d.error ?? '')}</p>
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  // ── Generic fallback for unhandled event types ───────────────────────

  const level = String(d.level ?? (d.step === 'error' ? 'error' : ''))
  const isError = level === 'error' || d.status === 'failed' || event.event_type.includes('error') || event.event_type.includes('failed')
  const isWarning = level === 'warning'
  const message = String(d.message ?? d.content ?? d.summary ?? '')

  if (isError) {
    return (
      <div className="mx-8 flex items-start gap-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-1.5 text-xs">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-red-400" />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-red-400">{eventLabel(event.event_type, d as Record<string, unknown>)}</span>
          {message && <p className="mt-0.5 text-red-300/80">{message}</p>}
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (isWarning) {
    return (
      <div className="mx-8 flex items-start gap-2 rounded border border-amber-500/20 bg-amber-500/5 px-3 py-1.5 text-xs">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-amber-400">{eventLabel(event.event_type, d as Record<string, unknown>)}</span>
          {message && <p className="mt-0.5 text-amber-300/80">{message}</p>}
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  const label = event.event_type.replace(/\./g, ' ')
  return (
    <div className="mx-8 flex items-center gap-2 px-1 text-xs text-muted-foreground/50">
      <Info className="h-3 w-3 shrink-0" />
      <span>{label}</span>
      {message && <span className="truncate text-muted-foreground/40">{message}</span>}
      <span className="ml-auto shrink-0 text-[10px] tabular-nums">{ts}</span>
    </div>
  )
}

export function MessageBubble({ message }: { message: SessionMessage }) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'
  const isStreaming = message.status === 'streaming'
  const isFailed = message.status === 'failed'
  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div className="mt-1 shrink-0">
        {isUser ? <User className="h-5 w-5 text-muted-foreground" />
          : isError || isFailed ? <AlertTriangle className="h-5 w-5 text-destructive" />
          : <Bot className="h-5 w-5 text-primary" />}
      </div>
      <div className={cn(
        'max-w-[75%] rounded-lg p-3',
        isUser ? 'bg-primary text-primary-foreground'
          : isError || isFailed ? 'border border-destructive/20 bg-destructive/10'
          : isStreaming ? 'border border-primary/20 bg-muted/50'
          : 'bg-muted/50',
      )}>
        {message.thinking && (
          <details open className="mb-3 rounded border border-purple-500/20 bg-purple-500/5 px-3 py-2">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-purple-400">
              <Brain className="h-3 w-3" />Thinking
            </summary>
            <p className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-muted-foreground">
              {message.thinking}
            </p>
          </details>
        )}
        {isUser
          ? <p className="whitespace-pre-wrap text-[13px]">{message.content}</p>
          : <MarkdownRenderer content={message.content} className="text-[13px]" />}
        {isStreaming && (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>Still generating...</span>
          </div>
        )}
        <div className={cn(
          'mt-1 flex items-center gap-2 text-[10px]',
          isUser ? 'text-primary-foreground/60' : 'text-muted-foreground',
        )}>
          <span>{formatUtc(message.created_at)}</span>
          {!isUser && message.sender_id && (
            <Badge variant="outline" className="text-[9px]">
              {message.sender_id.replace('.agent', '').split('.').pop()}
            </Badge>
          )}
          {message.cost_usd != null && (
            <Badge variant="secondary" className="text-[9px]">${message.cost_usd.toFixed(4)}</Badge>
          )}
        </div>
      </div>
    </div>
  )
}
