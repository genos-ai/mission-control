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

import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  MessageSquare,
  Plus,
  Loader2,
  Bot,
  Brain,
  ChevronDown,
  ChevronLeft,
  Zap,
} from 'lucide-react'
import { formatUtc } from '@/lib/format-date'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { useTeam } from '@/hooks/use-team'
import { useSessions, useCreateSession } from '@/hooks/use-sessions'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { agentStyle } from '@/lib/agent-tone'
import { DEFAULT_CHAT_AGENT } from './chat-constants'
import { Conversation } from './chat-conversation'
import { ToolOutputPanel } from './chat-artifacts-panel'

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function ChatTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [rightOpen, setRightOpen] = useState(true)
  const [activeAgent, setActiveAgent] = useState<string>(DEFAULT_CHAT_AGENT)
  const { user } = useAuthStore()

  // Shared session for the mission (one session, all agents)
  const { data: sessions, isLoading: loadingSessions } = useSessions({ mission_id: missionId, status: 'active' })
  const createSession = useCreateSession()
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)

  // Auto-select the most recent session
  useEffect(() => {
    if (sessions && sessions.length > 0 && !activeSessionId) {
      setActiveSessionId(sessions[0].id)
    }
  }, [sessions]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset agent and session on mission change
  const prevId = useRef<string | null>(null)
  useEffect(() => {
    if (missionId && missionId !== prevId.current) {
      prevId.current = missionId
      setActiveAgent(DEFAULT_CHAT_AGENT)
      setActiveSessionId(null)
    }
  }, [missionId])

  async function handleNewThread() {
    if (!user || !missionId) return
    try {
      const session = await createSession.mutateAsync({
        goal: 'Mission Chat',
        mission_id: missionId,
        agent_id: DEFAULT_CHAT_AGENT,
      })
      setActiveSessionId(session.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create session')
    }
  }

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
        <ThreadSelector
          sessions={sessions ?? []}
          activeSessionId={activeSessionId}
          onSelect={setActiveSessionId}
          onNewThread={handleNewThread}
          loading={loadingSessions || createSession.isPending}
        />
        <AgentChatPanel
          missionId={missionId!}
          agentName={activeAgent}
          sessionId={activeSessionId}
          onReturnToDirector={() => setActiveAgent(DEFAULT_CHAT_AGENT)}
          onNewThread={handleNewThread}
          loading={loadingSessions || createSession.isPending}
        />
      </div>

      {/* Right — tool output */}
      {rightOpen ? (
        <ToolOutputPanel
          activeAgent={activeAgent}
          activeSessionId={activeSessionId}
          onClose={() => setRightOpen(false)}
        />
      ) : (
        <button
          onClick={() => setRightOpen(true)}
          className="flex w-5 shrink-0 items-center justify-center border-l text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
          title="Open outputs panel"
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
      <RosterRow
        agentName={DEFAULT_CHAT_AGENT}
        live={agentStatuses[DEFAULT_CHAT_AGENT]}
        active={activeAgent === DEFAULT_CHAT_AGENT}
        chatEnabled
        onClick={() => onAgentClick(DEFAULT_CHAT_AGENT)}
        pinned
      />
      <div className="flex-1 overflow-y-auto py-1">
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
  pinned,
}: {
  agentName: string
  live?: { status: string; currentTool: string | null }
  active: boolean
  chatEnabled: boolean
  onClick: () => void
  pinned?: boolean
}) {
  const status = live?.status ?? 'idle'
  const isBusy = status === 'thinking' || status === 'running'
  const CapabilityIcon = agentStyle(agentName).icon

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
        'group flex w-full flex-col px-3 text-left transition-colors',
        pinned ? 'h-9 shrink-0 justify-center border-b' : 'py-2',
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
      {live?.currentTool ? (
        <p className="ml-4 mt-0.5 truncate text-[11px] text-amber-400/80">
          ↳ {live.currentTool}
        </p>
      ) : live?.status === 'thinking' ? (
        <p className="ml-4 mt-0.5 truncate text-[11px] text-muted-foreground/50 animate-pulse">
          ↳ thinking…
        </p>
      ) : null}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Thread selector — shared session picker at top level
// ---------------------------------------------------------------------------

function ThreadSelector({
  sessions,
  activeSessionId,
  onSelect,
  onNewThread,
  loading,
}: {
  sessions: { id: string; goal?: string | null; last_activity_at?: string | null }[]
  activeSessionId: string | null
  onSelect: (id: string) => void
  onNewThread: () => void
  loading: boolean
}) {
  return (
    <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3 bg-muted/30">
      <span className="text-[10px] font-medium text-muted-foreground">Thread:</span>
      <div className="relative">
        <select
          value={activeSessionId ?? ''}
          onChange={(e) => onSelect(e.target.value)}
          className="h-6 appearance-none rounded border bg-transparent pl-2 pr-6 text-[10px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.goal || s.id.slice(0, 12)} · {formatUtc(s.last_activity_at)}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-1.5 top-1 h-3 w-3 text-muted-foreground" />
      </div>
      <Button
        variant="ghost" size="icon" className="h-6 w-6 shrink-0"
        onClick={onNewThread} disabled={loading} title="New thread"
      >
        {loading
          ? <Loader2 className="h-3 w-3 animate-spin" />
          : <Plus className="h-3 w-3" />}
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent chat panel — receives shared session, routes by target agent
// ---------------------------------------------------------------------------

function AgentChatPanel({
  missionId,
  agentName,
  sessionId,
  onReturnToDirector,
  onNewThread,
  loading,
}: {
  missionId: string
  agentName: string
  sessionId: string | null
  onReturnToDirector: () => void
  onNewThread: () => void
  loading: boolean
}) {
  const agentShort = agentName.endsWith('.agent') ? agentName.slice(0, -6) : agentName
  const isDirector = agentName === DEFAULT_CHAT_AGENT

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
      </div>

      {/* Conversation */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : sessionId ? (
          <Conversation sessionId={sessionId} missionId={missionId} targetAgent={agentName} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <Bot className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-center text-sm text-muted-foreground">
              Start a conversation with <span className="font-medium">{agentShort}</span>.
            </p>
            <Button variant="outline" size="sm" onClick={onNewThread}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />New Chat
            </Button>
          </div>
        )}
      </div>
    </>
  )
}
