/**
 * ChatTab — 3-panel mission chat experience.
 *
 * Left  (220px) — Director (pinned) + live team roster
 * Center (flex) — Agent conversation
 * Right (280px) — Artifact cards (expanded by default, human can collapse)
 *
 * This is the only mission tab with the full 3-panel layout. All other tabs
 * render full-width content. The SSE connection and stores are owned by
 * MissionLayout; this tab only reads from them.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  MessageSquare,
  Plus,
  Send,
  Loader2,
  Bot,
  User,
  Brain,
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Package,
  Zap,
  GitBranch,
  FileText,
  Activity,
  Layers,
  Sparkles,
  ShieldCheck,
  CheckCircle2,
  ListTodo,
  type LucideIcon,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { useTeam } from '@/hooks/use-team'
import { useSessions, useMessages, useCreateSession, sessionKeys } from '@/hooks/use-sessions'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore, type StreamingArtifact } from '@/stores/workspace'
import { useMissionArtifacts, type MissionArtifact } from '@/hooks/use-mission-artifacts'
import { useResizable } from '@/hooks/use-resizable'
import { queryClient } from '@/main'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { API_BASE } from '@/lib/constants'
import type { SessionMessage } from '@/types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_CHAT_AGENT = 'mission.director.agent'

const AGENT_ICONS: Record<string, LucideIcon> = {
  'mission.director.agent':       Brain,
  'platform.director.agent':      Brain,
  'mission.workflow.agent':       GitBranch,
  'platform.health.agent':        Activity,
  'software.architecture.agent':  Layers,
  'software.quality.agent':       ShieldCheck,
  'system.planning.agent':        ListTodo,
  'system.summarization.agent':   FileText,
  'system.synthesis.agent':       Sparkles,
  'system.verification.agent':    CheckCircle2,
}

function getAgentIcon(name: string): LucideIcon {
  return AGENT_ICONS[name] ?? Bot
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function ChatTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [rightOpen, setRightOpen] = useState(true)
  const [activeAgent, setActiveAgent] = useState<string>(DEFAULT_CHAT_AGENT)

  // Reset to Director on mission change
  const prevId = useRef<string | null>(null)
  useEffect(() => {
    if (missionId && missionId !== prevId.current) {
      prevId.current = missionId
      setActiveAgent(DEFAULT_CHAT_AGENT)
    }
  }, [missionId])

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left — agent roster */}
      <LeftPanel
        missionId={missionId!}
        activeAgent={activeAgent}
        onAgentClick={setActiveAgent}
      />

      {/* Center — agent chat */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l">
        <AgentChatPanel
          key={activeAgent}
          missionId={missionId!}
          agentName={activeAgent}
          onReturnToDirector={() => setActiveAgent(DEFAULT_CHAT_AGENT)}
        />
      </div>

      {/* Right — artifacts */}
      {rightOpen ? (
        <ArtifactsPanel missionId={missionId!} onClose={() => setRightOpen(false)} />
      ) : (
        <button
          onClick={() => setRightOpen(true)}
          className="flex w-5 shrink-0 items-center justify-center border-l text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
          title="Open artifacts panel"
        >
          <ChevronLeft className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Left panel — live agent roster
// ---------------------------------------------------------------------------

function LeftPanel({
  missionId,
  activeAgent,
  onAgentClick,
}: {
  missionId: string
  activeAgent: string
  onAgentClick: (name: string) => void
}) {
  const { data: team, isLoading } = useTeam(missionId)
  const agentStatuses = useWorkspaceStore((s) => s.agentStatuses)

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-r">
      <div className="flex h-9 shrink-0 items-center border-b px-3">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Team
        </span>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        <RosterRow
          agentName={DEFAULT_CHAT_AGENT}
          live={agentStatuses[DEFAULT_CHAT_AGENT]}
          active={activeAgent === DEFAULT_CHAT_AGENT}
          chatEnabled
          onClick={() => onAgentClick(DEFAULT_CHAT_AGENT)}
        />
        <div className="mx-3 my-1 border-t border-border/50" />
        {isLoading && (
          <div className="flex justify-center py-4">
            <Spinner className="h-4 w-4" />
          </div>
        )}
        {team
          ?.filter((m) => (m.agent?.agent_name ?? m.agent_catalog_id) !== DEFAULT_CHAT_AGENT)
          .map((member) => {
            const agentName = member.agent?.agent_name ?? member.agent_catalog_id
            return (
              <RosterRow
                key={member.agent_catalog_id}
                agentName={agentName}
                live={agentStatuses[agentName]}
                active={activeAgent === agentName}
                chatEnabled={member.agent?.chat_enabled ?? false}
                onClick={() => onAgentClick(agentName)}
              />
            )
          })}
        {!isLoading && (!team || team.length === 0) && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No other agents assigned</p>
        )}
      </div>
    </div>
  )
}

function RosterRow({
  agentName,
  live,
  active,
  chatEnabled,
  onClick,
}: {
  agentName: string
  live?: { status: string; currentTool: string | null }
  active: boolean
  chatEnabled: boolean
  onClick: () => void
}) {
  const status = live?.status ?? 'idle'
  const isBusy = status === 'thinking' || status === 'running'
  const CapabilityIcon = getAgentIcon(agentName)

  const capabilityIconClass =
    status === 'running'  ? 'text-amber-400 animate-pulse' :
    status === 'thinking' ? 'text-purple-400 animate-pulse' :
    status === 'done'     ? 'text-emerald-400' :
    status === 'failed'   ? 'text-destructive' :
    chatEnabled           ? 'text-muted-foreground/60' :
                            'text-muted-foreground/30'

  let trailingIcon: React.ReactNode = null
  if (chatEnabled) {
    if (isBusy) {
      trailingIcon = (
        <Zap className={cn(
          'ml-auto h-3 w-3 shrink-0 animate-pulse',
          status === 'running' ? 'text-amber-400' : 'text-purple-400',
        )} />
      )
    } else if (active) {
      trailingIcon = <MessageSquare className="ml-auto h-3 w-3 shrink-0 text-primary" />
    } else {
      trailingIcon = (
        <MessageSquare className="ml-auto h-3 w-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/60" />
      )
    }
  }

  const sName = agentName.endsWith('.agent') ? agentName.slice(0, -6) : agentName

  return (
    <button
      onClick={onClick}
      disabled={!chatEnabled}
      className={cn(
        'group flex w-full flex-col px-3 py-2 text-left transition-colors',
        active && 'bg-primary/10',
        chatEnabled && !active && 'hover:bg-accent/50',
        !chatEnabled && 'cursor-default',
      )}
      title={chatEnabled ? `Chat with ${sName}` : `${sName} — task agent (not chat-enabled)`}
    >
      <div className="flex items-center gap-2">
        <CapabilityIcon className={cn('h-3.5 w-3.5 shrink-0', capabilityIconClass)} />
        <span
          className={cn(
            'truncate text-[13px]',
            chatEnabled ? 'text-foreground' : 'text-muted-foreground/60',
          )}
          title={agentName}
        >
          {sName}
        </span>
        {trailingIcon}
      </div>
      {live?.currentTool && (
        <p className="ml-4 mt-0.5 truncate text-[11px] text-amber-400/80">
          ↳ {live.currentTool}
        </p>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Agent chat panel
// ---------------------------------------------------------------------------

function AgentChatPanel({
  missionId,
  agentName,
  onReturnToDirector,
}: {
  missionId: string
  agentName: string
  onReturnToDirector: () => void
}) {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const { user } = useAuthStore()
  const { data: allSessions, isLoading: loadingSessions } = useSessions({ mission_id: missionId })
  const createSession = useCreateSession()

  const agentShort = agentName.endsWith('.agent') ? agentName.slice(0, -6) : agentName
  const isDirector = agentName === DEFAULT_CHAT_AGENT
  const sessions = allSessions?.filter((s) => s.agent_id === agentName) ?? []

  useEffect(() => {
    if (!selectedSessionId && sessions.length > 0) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions.length]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleNewChat() {
    if (!user) return
    try {
      const session = await createSession.mutateAsync({
        goal: `${agentShort} Chat`,
        mission_id: missionId,
        agent_id: agentName,
      })
      setSelectedSessionId(session.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create session')
    }
  }

  return (
    <>
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3">
        {!isDirector && (
          <button
            onClick={onReturnToDirector}
            className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
            title="Back to Director"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        )}
        {isDirector
          ? <Brain className="h-3.5 w-3.5 text-primary" />
          : <Bot className="h-3.5 w-3.5 text-muted-foreground" />
        }
        <span className="text-xs font-semibold">
          {isDirector ? 'Director' : agentShort}
        </span>

        <div className="relative ml-auto">
          <select
            value={selectedSessionId ?? ''}
            onChange={(e) => setSelectedSessionId(e.target.value || null)}
            className="h-6 appearance-none rounded border bg-transparent pl-2 pr-6 text-[10px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">— thread —</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.goal || s.id.slice(0, 12)} ·{' '}
                {formatDistanceToNow(new Date(s.last_activity_at), { addSuffix: true })}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1.5 top-1 h-3 w-3 text-muted-foreground" />
        </div>
        <Button
          variant="ghost" size="icon" className="h-6 w-6 shrink-0"
          onClick={handleNewChat} disabled={createSession.isPending} title="New thread"
        >
          {createSession.isPending
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <Plus className="h-3 w-3" />}
        </Button>
      </div>

      {/* Conversation */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {loadingSessions ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : selectedSessionId ? (
          <Conversation sessionId={selectedSessionId} missionId={missionId} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <Bot className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-center text-sm text-muted-foreground">
              Start a conversation with <span className="font-medium">{agentShort}</span>.
            </p>
            <Button variant="outline" size="sm" onClick={handleNewChat}
              disabled={createSession.isPending}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />New Chat
            </Button>
          </div>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Conversation view
// ---------------------------------------------------------------------------

function Conversation({ sessionId, missionId }: { sessionId: string; missionId: string }) {
  const { data: history, isLoading } = useMessages(sessionId)
  const { user } = useAuthStore()
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingThinking, setStreamingThinking] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setMessages([])
    setStreamingContent('')
    setStreamingThinking('')
    setSending(false)
    abortRef.current?.abort()
    abortRef.current = null
  }, [sessionId])

  useEffect(() => { if (history) setMessages(history) }, [history])
  useEffect(() => () => { abortRef.current?.abort() }, [])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, streamingContent, streamingThinking])

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
        thinking: null, created_at: new Date().toISOString(),
      },
    ])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = useAuthStore.getState().accessToken
      const response = await fetch(
        `${API_BASE}/sessions/${sessionId}/messages?mission_id=${missionId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ content, role: 'user', sender_id: user?.id }),
          signal: controller.signal,
        },
      )
      if (!response.ok) throw new Error('Failed to send message')

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6)
          if (raw === '{}') continue
          try {
            const ev = JSON.parse(raw)
            if (ev.event_type === 'agent.response.chunk') {
              if (ev.metadata?.thinking) setStreamingThinking((p) => p + (ev.content ?? ''))
              else { accumulated += ev.content ?? ''; setStreamingContent(accumulated) }
            } else if (ev.event_type === 'agent.response.complete') {
              setMessages((p) => [
                ...p,
                {
                  id: `resp-${Date.now()}`, session_id: sessionId,
                  role: ev.metadata?.error ? 'error' : 'assistant',
                  content: ev.full_content ?? accumulated,
                  sender_id: ev.agent_id ?? null, model: ev.model ?? null,
                  input_tokens: ev.input_tokens ?? null, output_tokens: ev.output_tokens ?? null,
                  cost_usd: ev.cost_usd ?? null, tool_name: null, tool_call_id: null,
                  thinking: ev.metadata?.thinking ?? null, created_at: new Date().toISOString(),
                },
              ])
              accumulated = ''
              setStreamingContent('')
              setStreamingThinking('')
            }
          } catch { /* skip malformed SSE line */ }
        }
      }
      if (accumulated) {
        setMessages((p) => [
          ...p,
          {
            id: `resp-${Date.now()}`, session_id: sessionId, role: 'assistant', content: accumulated,
            sender_id: null, model: null, input_tokens: null, output_tokens: null, cost_usd: null,
            tool_name: null, tool_call_id: null, thinking: null, created_at: new Date().toISOString(),
          },
        ])
        setStreamingContent('')
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      toast.error(err instanceof Error ? err.message : 'Send failed')
    } finally {
      abortRef.current = null
      setSending(false)
      queryClient.invalidateQueries({ queryKey: sessionKeys.messages(sessionId) })
    }
  }, [input, sending, sessionId, missionId, user?.id])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendMessage() }
  }

  if (isLoading) return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  )

  return (
    <>
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages
          .filter((m) => m.role === 'user' || m.role === 'assistant' || m.role === 'error')
          .map((msg) => <MessageBubble key={msg.id} message={msg} />)}

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
                  <MarkdownRenderer content={streamingContent} className="text-sm" />
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
      </div>

      <div className="shrink-0 border-t p-3">
        <div className="flex gap-2">
          <Textarea
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message… (Cmd+Enter)"
            rows={2} className="resize-none text-sm" disabled={sending}
          />
          <Button size="icon" onClick={sendMessage}
            disabled={!input.trim() || sending} className="h-auto">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">Cmd+Enter to send</p>
      </div>
    </>
  )
}

function MessageBubble({ message }: { message: SessionMessage }) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'
  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div className="mt-1 shrink-0">
        {isUser ? <User className="h-5 w-5 text-muted-foreground" />
          : isError ? <AlertTriangle className="h-5 w-5 text-destructive" />
          : <Bot className="h-5 w-5 text-primary" />}
      </div>
      <div className={cn(
        'max-w-[75%] rounded-lg p-3',
        isUser ? 'bg-primary text-primary-foreground'
          : isError ? 'border border-destructive/20 bg-destructive/10'
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
          ? <p className="whitespace-pre-wrap text-sm">{message.content}</p>
          : <MarkdownRenderer content={message.content} className="text-sm" />}
        <div className={cn(
          'mt-1 flex items-center gap-2 text-[10px]',
          isUser ? 'text-primary-foreground/60' : 'text-muted-foreground',
        )}>
          <span>{formatDistanceToNow(new Date(message.created_at), { addSuffix: true })}</span>
          {message.cost_usd != null && (
            <Badge variant="secondary" className="text-[9px]">${message.cost_usd.toFixed(4)}</Badge>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Right panel — artifact cards
// ---------------------------------------------------------------------------

function ArtifactsPanel({ missionId, onClose }: { missionId: string; onClose: () => void }) {
  // Durable artifacts via react-query (Plan 43). SSE invalidation wired
  // in layout.tsx — the query refetches when mission.artifact.found
  // fires, so newly persisted rows appear live without a page refresh.
  const { data: artifacts = [], isLoading } = useMissionArtifacts(missionId)
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  const hasContent = streaming || artifacts.length > 0
  const { width, onMouseDown } = useResizable(280)

  return (
    <div className="relative flex shrink-0 flex-col border-l" style={{ width }}>
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/20 transition-colors z-10"
      />
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium">Artifacts</span>
          {streaming && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
              live
            </span>
          )}
          {!streaming && artifacts.length > 0 && (
            <span className="text-[10px] text-muted-foreground/60">
              {artifacts.length}
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

      <div className="flex-1 overflow-y-auto">
        {isLoading && !streaming ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground/50" />
          </div>
        ) : !hasContent ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 py-8">
            <Package className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs leading-relaxed text-muted-foreground/70">
              No artifacts yet.
            </p>
            <p className="max-w-[220px] text-center text-[11px] leading-relaxed text-muted-foreground/50">
              Artifacts appear here when agents produce reports, findings, or code during a run. They are persisted across sessions and survive backend restarts.
            </p>
          </div>
        ) : (
          <div className="space-y-px p-2">
            {streaming && <StreamingArtifactCard streaming={streaming} />}
            {artifacts.map((a) => (
              <ArtifactCard key={a.id} artifact={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StreamingArtifactCard({ streaming }: { streaming: StreamingArtifact }) {
  const agentShort = streaming.agentId.endsWith('.agent')
    ? streaming.agentId.slice(0, -6)
    : streaming.agentId
  return (
    <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
        <span className="font-medium text-amber-400">{agentShort}</span>
        <span className="text-muted-foreground/60">writing…</span>
      </div>
      <div className="max-h-48 overflow-y-auto">
        <MarkdownRenderer content={streaming.content} className="text-[11px]" />
      </div>
    </div>
  )
}

function ArtifactCard({ artifact }: { artifact: MissionArtifact }) {
  const content = artifact.content_text ?? ''
  const agentShort = artifact.agent_id.endsWith('.agent')
    ? artifact.agent_id.slice(0, -6)
    : artifact.agent_id
  return (
    <details className="group rounded border border-violet-500/15 bg-violet-500/5 p-2 text-xs">
      <summary className="flex cursor-pointer list-none items-start gap-1.5">
        <Package className="mt-0.5 h-3 w-3 shrink-0 text-violet-400" />
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-snug">{artifact.title}</p>
          <p className="text-[10px] text-muted-foreground/60">
            {agentShort}
            {' · '}{artifact.artifact_type}
          </p>
        </div>
        <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 border-t border-violet-500/15 pt-2">
        <MarkdownRenderer content={content} className="text-xs" />
      </div>
    </details>
  )
}
