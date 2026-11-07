/**
 * ChatTab — 3-panel mission chat experience.
 *
 * Left   — Director (pinned) + live team roster
 * Center — Agent conversation
 * Right  — Tool outputs (collapsible)
 *
 * This is the only mission tab with the full 3-panel layout. All other tabs
 * render full-width content. The SSE connection and stores are owned by
 * MissionLayout; this tab only reads from them.
 */

import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Bot, ChevronDown, ChevronLeft, Loader2, PanelRightOpen, Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { agentStyle } from '@/lib/agent-tone'
import { agentShortName } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import type { Tone } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import { useTeam } from '@/hooks/use-team'
import { useSessions, useCreateSession } from '@/hooks/use-sessions'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore, type AgentStatusEntry } from '@/stores/workspace'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { Select } from '@/components/ui/select'
import { agentLabel, DEFAULT_CHAT_AGENT } from './chat-constants'
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
    <div className="flex h-full gap-gutter overflow-hidden px-2 pb-2">
      <LeftPanel
        missionId={missionId!}
        activeAgent={activeAgent}
        onAgentClick={setActiveAgent}
      />

      <AgentChatPanel
        missionId={missionId!}
        agentName={activeAgent}
        sessionId={activeSessionId}
        sessions={sessions ?? []}
        onSelectSession={setActiveSessionId}
        onReturnToDirector={() => setActiveAgent(DEFAULT_CHAT_AGENT)}
        onNewThread={handleNewThread}
        loading={loadingSessions || createSession.isPending}
      />

      {rightOpen ? (
        <ToolOutputPanel
          activeAgent={activeAgent}
          activeSessionId={activeSessionId}
          onClose={() => setRightOpen(false)}
        />
      ) : (
        <button
          onClick={() => setRightOpen(true)}
          aria-label="Open outputs panel"
          title="Open outputs panel"
          className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-control text-subtle transition-colors duration-150 hover:bg-raised hover:text-foreground min-[1200px]:flex"
        >
          <PanelRightOpen className="h-4 w-4" />
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
    <Panel className="hidden w-[228px] shrink-0 flex-col gap-0.5 overflow-y-auto px-2 py-3 min-[960px]:flex">
      <div className="px-2 pb-2 text-xs text-subtle">Talk to</div>
      <RosterRow
        agentName={DEFAULT_CHAT_AGENT}
        live={agentStatuses[DEFAULT_CHAT_AGENT]}
        active={activeAgent === DEFAULT_CHAT_AGENT}
        chatEnabled
        onClick={() => onAgentClick(DEFAULT_CHAT_AGENT)}
        pinned
      />
      {isLoading && (
        <div className="flex justify-center py-4">
          <Spinner />
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
        <p className="px-2 py-2 text-xs text-subtle">No other agents assigned</p>
      )}
    </Panel>
  )
}

/** The second line of a roster row: what the agent is doing right now, or its role. */
function rosterNote(
  live: AgentStatusEntry | undefined,
  chatEnabled: boolean,
  pinned: boolean,
): { text: string; tone: Tone; mono: boolean } {
  switch (live?.status) {
    case 'running':
      return { text: live.currentTool ?? 'running', tone: 'warning', mono: live.currentTool != null }
    case 'thinking':
      return { text: 'thinking…', tone: 'violet', mono: false }
    case 'done':
      return { text: 'Done', tone: 'success', mono: false }
    case 'failed':
      return { text: 'Failed', tone: 'danger', mono: false }
    default:
      if (pinned) return { text: 'Mission lead', tone: 'brand', mono: false }
      return { text: chatEnabled ? 'Idle' : 'Task agent', tone: 'neutral', mono: false }
  }
}

function RosterRow({
  agentName,
  live,
  active,
  chatEnabled,
  onClick,
  pinned = false,
}: {
  agentName: string
  live?: AgentStatusEntry
  active: boolean
  chatEnabled: boolean
  onClick: () => void
  pinned?: boolean
}) {
  const style = agentStyle(agentName)
  const note = rosterNote(live, chatEnabled, pinned)
  const working = live?.status === 'thinking' || live?.status === 'running'
  const name = agentShortName(agentName)

  return (
    <button
      onClick={onClick}
      disabled={!chatEnabled}
      className={cn(
        'flex w-full items-start gap-2.5 rounded-card p-2 text-left transition-colors duration-150',
        active && 'bg-sidebar-active',
        chatEnabled && !active && 'hover:bg-raised',
        !chatEnabled && 'cursor-default opacity-60',
      )}
      title={chatEnabled ? `Chat with ${name}` : `${name} — task agent (not chat-enabled)`}
    >
      <IconTile icon={style.icon} tone={style.tone} size="sm" live={working} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm" title={agentName}>{name}</span>
        <span className={cn('block truncate text-2xs', TONE_TEXT[note.tone], note.mono && 'font-mono')}>
          {note.text}
        </span>
      </span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Agent chat panel — header (agent, thread picker, new thread) and the conversation
// ---------------------------------------------------------------------------

interface SessionOption {
  id: string
  goal?: string | null
  last_activity_at?: string | null
}

function ThreadPicker({
  sessions,
  activeSessionId,
  onSelect,
}: {
  sessions: SessionOption[]
  activeSessionId: string | null
  onSelect: (id: string) => void
}) {
  if (sessions.length === 0) return null
  return (
    <div className="relative">
      <Select
        aria-label="Thread"
        value={activeSessionId ?? ''}
        onChange={(e) => onSelect(e.target.value)}
        variant="pill"
      >
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>
            {s.goal || s.id.slice(0, 12)} · {formatUtc(s.last_activity_at)}
          </option>
        ))}
      </Select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1.5 h-3 w-3 text-subtle" />
    </div>
  )
}

function AgentChatPanel({
  missionId,
  agentName,
  sessionId,
  sessions,
  onSelectSession,
  onReturnToDirector,
  onNewThread,
  loading,
}: {
  missionId: string
  agentName: string
  sessionId: string | null
  sessions: SessionOption[]
  onSelectSession: (id: string) => void
  onReturnToDirector: () => void
  onNewThread: () => void
  loading: boolean
}) {
  const label = agentLabel(agentName)
  const isDirector = agentName === DEFAULT_CHAT_AGENT

  return (
    <Panel className="flex min-w-[320px] flex-1 flex-col overflow-hidden">
      <div className="flex h-12 shrink-0 items-center gap-2.5 px-5 pt-1">
        {!isDirector && (
          <button
            onClick={onReturnToDirector}
            aria-label="Back to Director"
            title="Back to Director"
            className="shrink-0 text-subtle transition-colors duration-150 hover:text-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        )}
        <span className="text-base font-medium">{label}</span>
        <ThreadPicker sessions={sessions} activeSessionId={sessionId} onSelect={onSelectSession} />
        <Button variant="pill" size="sm" className="ml-auto" onClick={onNewThread} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" /> : <Plus className="h-3 w-3" />}
          New thread
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner className="h-5 w-5" />
          </div>
        ) : sessionId ? (
          <Conversation sessionId={sessionId} missionId={missionId} targetAgent={agentName} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <Bot className="h-8 w-8 text-faint" />
            <p className="text-center text-sm text-muted-foreground">
              Start a conversation with <span className="font-medium">{label}</span>.
            </p>
            <Button variant="secondary" onClick={onNewThread}>
              <Plus className="h-3.5 w-3.5" />
              New chat
            </Button>
          </div>
        )}
      </div>
    </Panel>
  )
}
