import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCatalogAgent } from '@/hooks/use-catalog'
import { SlashCommandPopover } from '@/components/chat/slash-command-popover'
import { ArrowUp, Loader2 } from 'lucide-react'
import { useBackgroundTasks } from '@/hooks/use-executions'
import toast from 'react-hot-toast'
import { api } from '@/lib/api'
import { useMessages, sessionKeys } from '@/hooks/use-sessions'
import { parseSseStream } from '@/hooks/use-sse'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { queryClient } from '@/lib/query-client'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { API_BASE } from '@/lib/constants'
import type { SessionMessage } from '@/types'
import { agentLabel, CHAT_HIDDEN_EVENT_TYPES, type TimelineEntry } from './chat-constants'
import { EventLine, InlineNarrativeRow } from './chat-events'
import { AgentMessage, MessageBubble, ThinkingBlock } from './chat-message'

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
  const agentTools = useMemo<string[]>(() => agentDetail?.tools ?? [], [agentDetail])
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

  // Keep the newest entry in view. This depends on the timeline, not on its inputs one by one:
  // historical events arrive from a separate query, and when they landed after the first scroll
  // they used to leave the thread stuck short of the bottom.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [timeline, streamingContent, streamingThinking])

  if (isLoading) return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  )

  const agentId = targetAgent ?? ''

  return (
    <>
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[720px] flex-col gap-[18px] px-6 py-7">
          {timeline.map((entry) =>
            entry.kind === 'message'
              ? <MessageBubble key={entry.data.id} message={entry.data} />
              : <InlineNarrativeRow key={entry.data.event_id} event={entry.data} />,
          )}

          {(streamingThinking || streamingContent) && (
            <AgentMessage agentId={agentId}>
              {streamingThinking && <ThinkingBlock text={streamingThinking.slice(-800)} live={!streamingContent} />}
              {streamingContent && (
                <>
                  <MarkdownRenderer content={streamingContent} className="text-md text-text-2 [overflow-wrap:anywhere]" />
                  <Loader2 className="mt-1 h-3 w-3 animate-spin text-subtle motion-reduce:animate-none" />
                </>
              )}
            </AgentMessage>
          )}

          {sending && !streamingContent && !streamingThinking && (
            <AgentMessage agentId={agentId}>
              <div className="flex items-center gap-2 text-sm text-subtle">
                <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
                Thinking…
              </div>
            </AgentMessage>
          )}

          {!sending && bgTaskCount > 0 && (
            <EventLine icon={Loader2} tone="brand" spin>
              Working in background: {bgTasks.map((t) => t.task_type?.replace('_', ' ')).join(', ')}
            </EventLine>
          )}
        </div>
      </div>

      <div className="shrink-0 px-6 pb-5">
        <div className="relative mx-auto flex max-w-[720px] flex-col gap-2 rounded-panel border border-panel-border bg-raised px-3.5 pb-2.5 pt-3">
          {filteredTools.length > 0 && (
            <SlashCommandPopover
              tools={filteredTools}
              activeIndex={slashIndex}
              onSelect={handleSlashSelect}
            />
          )}
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${agentLabel(agentId)}…`}
            rows={2}
            className="min-h-0 resize-none border-0 bg-transparent p-0 focus:border-0 focus:ring-0"
            disabled={sending}
          />
          <div className="flex items-center gap-2 text-xs text-subtle">
            <Kbd>/</Kbd>
            commands
            <span className="ml-auto">⌘↵ to send</span>
            <Button
              size="icon"
              aria-label="Send message"
              onClick={sendMessage}
              disabled={!input.trim() || sending}
              className="h-7 w-7 rounded-control disabled:bg-faint disabled:opacity-100"
            >
              {sending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                : <ArrowUp className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
