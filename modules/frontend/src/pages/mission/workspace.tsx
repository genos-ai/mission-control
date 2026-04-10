/**
 * MissionWorkspace — conversational-first command center
 *
 * Three-panel layout:
 *   Left  (220px) — Director (pinned) + live team roster
 *   Center (flex) — Agent chat | Plan board | Narrative feed | Event stream
 *   Right (280px) — artifact cards (collapsed by default)
 *
 * The Director is auto-selected on mission landing, so every new mission
 * opens straight into a conversation — the human is greeted, can describe
 * the goal, review the plan, and approve execution. Clicking any other
 * agent in the roster swaps the center into that agent's chat. The Plan /
 * Narrative / Stream feed modes are reached via the back arrow.
 *
 * One SSE connection owned here, shared via MissionStreamContext so
 * ConsolePage (Stream mode) doesn't open a second connection.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Play,
  Pause,
  Archive,
  RotateCcw,
  Plus,
  Send,
  Loader2,
  Bot,
  User,
  Brain,
  AlertTriangle,
  ChevronDown,
  Package,
  Radio,
  Zap,
  Activity,
  Kanban,
  ListChecks,
  Settings2,
  GitBranch,
  FileText,
  Activity as ActivityIcon,
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
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useTeam } from '@/hooks/use-team'
import { useMissionStream } from '@/hooks/use-sse'
import { useSessions, useMessages, useCreateSession, sessionKeys } from '@/hooks/use-sessions'
import { planKeys } from '@/hooks/use-mission-plan'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { useWorkspaceStore, type StreamingArtifact } from '@/stores/workspace'
import { queryClient } from '@/main'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { RunModal } from '@/components/mission/run-modal'
import { API_BASE, ROUTES } from '@/lib/constants'
import { MissionStreamContext } from '@/context/mission-stream'
import type { MissionStatus, SessionMessage } from '@/types'

// Stream mode — existing console, reads from shared stream context
import ConsolePage from '@/pages/mission/console'
import { PlanBoard } from '@/components/workspace/plan-board'
import { RunsPanel } from '@/components/workspace/runs-panel'
import { MissionSettingsDrawer } from '@/components/workspace/mission-settings-drawer'
import { ContextPanel } from '@/components/workspace/context-panel'
import { WorkflowsPanel } from '@/components/workspace/workflows-panel'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_CHAT_AGENT = 'mission.director.agent'

/**
 * Capability icon per agent. Used as a visual shorthand in the left roster.
 *
 * NOTE: This mapping lives on the frontend for now. If you add a new agent
 * to the catalog, add its icon here too. Long-term, promote `ui_icon` to a
 * `config/agents/**​/agent.yaml` field + catalog column so adding an agent
 * doesn't need a frontend code change.
 */
const AGENT_ICONS: Record<string, LucideIcon> = {
  'mission.director.agent':       Brain,
  'platform.director.agent':      Brain,
  'mission.workflow.agent':       GitBranch,
  'platform.health.agent':        ActivityIcon,
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

const STATUS_VARIANT: Record<MissionStatus, 'success' | 'warning' | 'secondary'> = {
  active: 'success',
  paused: 'warning',
  archived: 'secondary',
}

function categorize(eventType: string): ConsoleEvent['category'] {
  if (
    eventType.startsWith('plan.') ||
    eventType.startsWith('agent.') ||
    eventType.startsWith('task.') ||
    eventType.startsWith('execution.') ||
    eventType.startsWith('decision.') ||
    eventType.startsWith('session.cost') ||
    eventType.startsWith('mission.')
  ) return 'execution'
  if (
    eventType.startsWith('user.message') ||
    eventType.startsWith('assistant.message')
  ) return 'chat'
  return 'system'
}

// ---------------------------------------------------------------------------
// Root workspace
// ---------------------------------------------------------------------------

export default function MissionWorkspace() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [rightOpen, setRightOpen] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Director chat is the default landing experience on every mission.
  const [activeAgentChat, setActiveAgentChat] = useState<string | null>(DEFAULT_CHAT_AGENT)

  const { data: mission } = useMission(id)
  const updateMission = useUpdateMission(id!)
  const { user } = useAuthStore()
  const isOwner = mission?.owner_id === user?.id

  // Clicking an agent row swaps the current chat subject AND jumps to Chat mode.
  const setFeedMode = useWorkspaceStore((s) => s.setFeedMode)
  function selectAgentChat(name: string) {
    setActiveAgentChat(name)
    setFeedMode('chat')
  }

  // Auto-open artifacts panel when streaming starts
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  useEffect(() => {
    if (streaming) setRightOpen(true)
  }, [!!streaming]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Single SSE connection, shared via context ──────────────────────────
  const { events: sseEvents, connected } = useMissionStream(id ?? null)

  // Route SSE events into both stores
  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)
  const onSseEvent = useWorkspaceStore((s) => s.onSseEvent)
  const resetWorkspace = useWorkspaceStore((s) => s.reset)
  const resetConsole = useConsoleStore((s) => s.reset)

  // Reset stores + land on Director chat on mission change
  const prevMissionId = useRef<string | null>(null)
  useEffect(() => {
    if (id && id !== prevMissionId.current) {
      prevMissionId.current = id
      resetWorkspace()
      resetConsole()
      setActiveAgentChat(DEFAULT_CHAT_AGENT)
    }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setConnected(connected) }, [connected, setConnected])

  // Forward new SSE events to both stores
  const processedCount = useRef(0)
  useEffect(() => {
    if (sseEvents.length > processedCount.current) {
      const newEvents = sseEvents.slice(processedCount.current)
      processedCount.current = sseEvents.length
      let planInvalidated = false
      newEvents.forEach((ev) => {
        const d = ev.data as Record<string, unknown>
        // workspace store (roster, artifacts, etc.)
        onSseEvent(ev.event_type, d)
        // console store (stream mode)
        addEvent({
          event_id: String(d.event_id ?? crypto.randomUUID()),
          event_type: ev.event_type,
          category: categorize(ev.event_type),
          timestamp: String(d.timestamp ?? new Date().toISOString()),
          source: String(d.agent_id ?? d.source ?? ''),
          data: d,
        })
        // Plan 42 §3.5: mission_plan.* events are invalidation signals
        // for the cached plan query. Coalesce to a single invalidation
        // per batch so a burst of task.status_changed events only
        // triggers one refetch.
        if (ev.event_type.startsWith('mission_plan.') && id) {
          planInvalidated = true
        }
      })
      if (planInvalidated && id) {
        queryClient.invalidateQueries({ queryKey: planKeys.plan(id) })
      }
    }
  }, [sseEvents.length]) // eslint-disable-line react-hooks/exhaustive-deps

  function setStatus(status: MissionStatus) {
    updateMission.mutate({ status })
  }

  const streamValue = { events: sseEvents, connected }

  return (
    <MissionStreamContext.Provider value={streamValue}>
      <div className="relative flex h-full flex-col overflow-hidden">

        {/* ── Top bar ───────────────────────────────────────────────── */}
        <div className="flex h-11 shrink-0 items-center justify-between border-b bg-card px-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              to={ROUTES.DASHBOARD}
              className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
              title="Back to dashboard"
            >
              <ChevronLeft className="h-4 w-4" />
            </Link>
            {mission ? (
              <>
                <span className="truncate text-sm font-semibold">{mission.name}</span>
                <Badge variant={STATUS_VARIANT[mission.status as MissionStatus]} className="shrink-0">
                  {mission.status}
                </Badge>
              </>
            ) : (
              <Spinner className="h-4 w-4" />
            )}
          </div>

          <div className="flex items-center gap-2">
            {isOwner && mission && (
              <>
                {mission.status === 'active' && (
                  <Button variant="outline" size="sm" className="h-7 text-xs"
                    onClick={() => setStatus('paused')}>
                    <Pause className="mr-1.5 h-3 w-3" />Pause
                  </Button>
                )}
                {mission.status === 'paused' && (
                  <Button variant="outline" size="sm" className="h-7 text-xs"
                    onClick={() => setStatus('active')}>
                    <RotateCcw className="mr-1.5 h-3 w-3" />Resume
                  </Button>
                )}
                {mission.status !== 'archived' && (
                  <Button variant="outline" size="sm" className="h-7 text-xs"
                    onClick={() => setStatus('archived')}>
                    <Archive className="mr-1.5 h-3 w-3" />Archive
                  </Button>
                )}
              </>
            )}
            <button
              onClick={() => setSettingsOpen(true)}
              className={cn(
                'rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground',
                settingsOpen && 'bg-accent text-foreground',
              )}
              title="Mission settings"
            >
              <Settings2 className="h-4 w-4" />
            </button>
            <Button size="sm" className="h-7 text-xs" onClick={() => setShowRunModal(true)}>
              <Play className="mr-1.5 h-3 w-3" />Run
            </Button>
          </div>
        </div>

        {/* ── Three panels ──────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* Left — live team roster */}
          <LeftPanel
            missionId={id!}
            onAgentClick={selectAgentChat}
            activeAgent={activeAgentChat}
          />

          {/* Center — Chat | Plan | Narrative | Stream */}
          <CenterPanel
            missionId={id!}
            agentChat={activeAgentChat ?? DEFAULT_CHAT_AGENT}
            onReturnToDirector={() => setActiveAgentChat(DEFAULT_CHAT_AGENT)}
          />

          {/* Right — artifacts */}
          {rightOpen ? (
            <ArtifactsPanel onClose={() => setRightOpen(false)} />
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

        {/* ── Mission Settings Drawer ──────────────────────────────── */}
        {settingsOpen && (
          <>
            <div
              className="absolute inset-0 z-40 bg-background/60 backdrop-blur-sm"
              onClick={() => setSettingsOpen(false)}
            />
            <div className="absolute inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l bg-card shadow-2xl">
              <MissionSettingsDrawer
                missionId={id!}
                onClose={() => setSettingsOpen(false)}
              />
            </div>
          </>
        )}

        {showRunModal && id && (
          <RunModal
            missionId={id}
            onClose={() => setShowRunModal(false)}
            onStarted={(executionId) => {
              setShowRunModal(false)
              navigate(ROUTES.MISSION_RUN_LIVE(id, executionId))
            }}
          />
        )}
      </div>
    </MissionStreamContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Left panel — live agent roster
// ---------------------------------------------------------------------------

function LeftPanel({
  missionId,
  onAgentClick,
  activeAgent,
}: {
  missionId: string
  onAgentClick: (agentName: string) => void
  activeAgent: string | null
}) {
  const { data: team, isLoading } = useTeam(missionId)
  const agentStatuses = useWorkspaceStore((s) => s.agentStatuses)
  const feedMode = useWorkspaceStore((s) => s.feedMode)

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-r">
      <div className="border-b px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Team
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {/* Director — always pinned first, whether or not it's in the team */}
        <RosterRow
          agentName={DEFAULT_CHAT_AGENT}
          live={agentStatuses[DEFAULT_CHAT_AGENT]}
          active={feedMode === 'chat' && activeAgent === DEFAULT_CHAT_AGENT}
          chatEnabled
          onClick={() => onAgentClick(DEFAULT_CHAT_AGENT)}
        />
        <div className="mx-3 my-1 border-t border-border/50" />

        {isLoading && (
          <div className="flex justify-center py-4"><Spinner className="h-4 w-4" /></div>
        )}
        {team
          ?.filter((m) => (m.agent?.agent_name ?? m.agent_catalog_id) !== DEFAULT_CHAT_AGENT)
          .map((member) => {
            const agentName = member.agent?.agent_name ?? member.agent_catalog_id
            const live = agentStatuses[agentName]
            // A row is "active" only when the Chat mode is actually open on it.
            const isActive = feedMode === 'chat' && activeAgent === agentName
            return (
              <RosterRow
                key={member.agent_catalog_id}
                agentName={agentName}
                live={live}
                active={isActive}
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

  // Capability icon, coloured by live status. Replaces the old status dot —
  // one glance tells you (a) what the agent does and (b) what it's doing now.
  const CapabilityIcon = getAgentIcon(agentName)
  const capabilityIconClass =
    status === 'running'  ? 'text-amber-400 animate-pulse' :
    status === 'thinking' ? 'text-purple-400 animate-pulse' :
    status === 'done'     ? 'text-emerald-400' :
    status === 'failed'   ? 'text-destructive' :
    chatEnabled           ? 'text-muted-foreground/60' :
                            'text-muted-foreground/30'

  // Trailing icon on the right:
  //  - chat-disabled rows: no icon at all (visually "read-only")
  //  - busy (thinking/running): Zap icon in the dot's colour ("this agent is working")
  //  - active chat subject: MessageSquare filled in primary ("you're chatting with them")
  //  - idle chat-enabled: MessageSquare faint, brightens on hover
  let trailingIcon: React.ReactNode = null
  if (chatEnabled) {
    if (isBusy) {
      trailingIcon = (
        <Zap
          className={cn(
            'ml-auto h-3 w-3 shrink-0 animate-pulse',
            status === 'running' ? 'text-amber-400' : 'text-purple-400',
          )}
        />
      )
    } else if (active) {
      trailingIcon = <MessageSquare className="ml-auto h-3 w-3 shrink-0 text-primary" />
    } else {
      trailingIcon = (
        <MessageSquare className="ml-auto h-3 w-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/60" />
      )
    }
  }

  const sName = agentName.endsWith('.agent')
    ? agentName.slice(0, -6)
    : agentName

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
      title={
        chatEnabled
          ? `Chat with ${sName}`
          : `${sName} — task agent (not chat-enabled)`
      }
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
// Center panel — mode toggle + Narrative | Stream
// ---------------------------------------------------------------------------

const FEED_MODES = [
  { id: 'chat',      label: 'Chat',      icon: Brain },
  { id: 'plan',      label: 'Plan',      icon: Kanban },
  { id: 'narrative', label: 'Narrative', icon: Radio },
  { id: 'stream',    label: 'Stream',    icon: Activity },
  { id: 'context',   label: 'Context',   icon: FileText },
  { id: 'runs',      label: 'Runs',      icon: ListChecks },
  { id: 'workflows', label: 'Workflows', icon: GitBranch },
] as const

function CenterPanel({
  missionId,
  agentChat,
  onReturnToDirector,
}: {
  missionId: string
  /** Current chat subject — never null; defaults to the Director. */
  agentChat: string
  /** Resets the current chat subject back to the Director. */
  onReturnToDirector: () => void
}) {
  const feedMode = useWorkspaceStore((s) => s.feedMode)
  const setFeedMode = useWorkspaceStore((s) => s.setFeedMode)

  // Clicking the Chat toggle while already in Chat mode jumps back to the
  // Director. Clicking it from another mode just enters Chat mode and keeps
  // whichever agent was previously selected.
  function handleModeClick(id: (typeof FEED_MODES)[number]['id']) {
    if (id === 'chat' && feedMode === 'chat') {
      onReturnToDirector()
      return
    }
    setFeedMode(id)
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l">
      {/* Mode toggle */}
      <div className="flex h-9 shrink-0 items-center gap-1 border-b px-3">
        <div className="flex items-center gap-0.5 rounded-md bg-muted/50 p-0.5">
          {FEED_MODES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => handleModeClick(id)}
              className={cn(
                'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
                feedMode === id
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              title={
                id === 'chat' && feedMode === 'chat'
                  ? 'Return to Director'
                  : undefined
              }
            >
              <Icon className="h-3 w-3" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {feedMode === 'chat' ? (
          <AgentChatPanel missionId={missionId} agentName={agentChat} />
        ) : feedMode === 'plan' ? (
          <PlanBoard missionId={missionId} />
        ) : feedMode === 'narrative' ? (
          <NarrativeFeed missionId={missionId} />
        ) : feedMode === 'stream' ? (
          <ConsolePage />
        ) : feedMode === 'context' ? (
          <ContextPanel missionId={missionId} />
        ) : feedMode === 'runs' ? (
          <RunsPanel missionId={missionId} />
        ) : (
          <WorkflowsPanel missionId={missionId} />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent chat panel — embedded in the center when an agent row is clicked
// ---------------------------------------------------------------------------

function AgentChatPanel({
  missionId,
  agentName,
}: {
  missionId: string
  agentName: string
}) {
  // Re-mount the session state whenever the agent subject changes so that
  // selected thread, draft message, and streaming buffers all reset cleanly.
  return (
    <AgentChatPanelInner
      key={agentName}
      missionId={missionId}
      agentName={agentName}
    />
  )
}

function AgentChatPanelInner({
  missionId,
  agentName,
}: {
  missionId: string
  agentName: string
}) {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const { user } = useAuthStore()
  const { data: allSessions, isLoading: loadingSessions } = useSessions({ mission_id: missionId })
  const createSession = useCreateSession()

  const agentShort = agentName.endsWith('.agent') ? agentName.slice(0, -6) : agentName
  const isDirector = agentName === DEFAULT_CHAT_AGENT

  // Sessions for this specific agent only
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
        {isDirector ? (
          <Brain className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Bot className="h-3.5 w-3.5 text-muted-foreground" />
        )}
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
          <DrawerConversation sessionId={selectedSessionId} missionId={missionId} />
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
// Narrative feed — curated human-readable mission events
// ---------------------------------------------------------------------------

const NARRATIVE_TYPES = new Set([
  'mission.narrative',
  'mission.artifact.found',
  'plan.step.started',
  'plan.step.completed',
  'agent.thinking.started',
  'agent.tool.called',
  'system.execution.created',
  'system.execution.completed',
])

function NarrativeFeed({ missionId: _missionId }: { missionId: string }) {
  const events = useConsoleStore((s) =>
    s.events.filter((e) => NARRATIVE_TYPES.has(e.event_type)),
  )
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoScroll = useConsoleStore((s) => s.autoScroll)

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events.length, autoScroll])

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3">
      {events.length === 0 && (
        <div className="flex h-full flex-col items-center justify-center gap-2">
          <Radio className="h-6 w-6 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground/60">
            Narrative events will appear here during a run.
          </p>
        </div>
      )}
      <div className="space-y-2">
        {events.map((ev) => (
          <NarrativeEventRow key={ev.event_id} event={ev} />
        ))}
      </div>
    </div>
  )
}

function NarrativeEventRow({ event }: { event: ConsoleEvent }) {
  const d = event.data
  const ts = formatTime(event.timestamp)

  if (event.event_type === 'mission.narrative') {
    const narrative = String(d.narrative ?? '')
    const level = String(d.level ?? 'info')
    const accent =
      level === 'success' ? 'border-l-emerald-500/60 bg-emerald-500/5' :
      level === 'warning'  ? 'border-l-amber-500/60 bg-amber-500/5' :
      'border-l-sky-500/40 bg-sky-500/5'
    return (
      <div className={cn('flex items-start gap-2.5 rounded border-l-2 px-3 py-2', accent)}>
        <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-400" />
        <div className="min-w-0 flex-1">
          <MarkdownRenderer content={narrative} className="text-sm" />
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'mission.artifact.found') {
    const title = String(d.title ?? 'Artifact')
    const content = String(d.content ?? '')
    const artifactType = String(d.artifact_type ?? 'report')
    return (
      <details className="group rounded border border-violet-500/20 bg-violet-500/5 px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center gap-2">
          <Package className="h-3.5 w-3.5 shrink-0 text-violet-400" />
          <span className="flex-1 text-sm font-medium">{title}</span>
          <Badge variant="outline" className="text-[9px] h-4">{artifactType}</Badge>
          <span className="text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-2 border-t border-violet-500/20 pt-2">
          <MarkdownRenderer content={content} className="text-sm" />
        </div>
      </details>
    )
  }

  if (event.event_type === 'agent.thinking.started') {
    const agent = String(d.agent_id ?? event.source ?? '')
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground/70">
        <Brain className="h-3 w-3 text-purple-400" />
        <span>{shortName(agent)} is thinking…</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'agent.tool.called') {
    const agent = String(d.agent_id ?? event.source ?? '')
    const tool = String(d.tool_name ?? '')
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground/70">
        <Zap className="h-3 w-3 text-amber-400" />
        <span>{shortName(agent)}</span>
        <span className="text-muted-foreground/40">→</span>
        <span className="font-medium text-amber-400/90">{tool}</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.started') {
    const stepName = String(d.step_name ?? d.step_id ?? '')
    return (
      <div className="flex items-center gap-2 rounded bg-blue-500/5 px-3 py-1.5 text-xs">
        <Activity className="h-3.5 w-3.5 shrink-0 text-blue-400" />
        <span className="font-medium">Starting</span>
        <span className="text-muted-foreground">{stepName}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.completed') {
    const status = String(d.status ?? 'success')
    const ok = status === 'success'
    return (
      <div className={cn(
        'flex items-center gap-2 rounded px-3 py-1.5 text-xs',
        ok ? 'bg-emerald-500/5' : 'bg-destructive/5',
      )}>
        <Activity className={cn('h-3.5 w-3.5 shrink-0', ok ? 'text-emerald-400' : 'text-destructive')} />
        <span className="font-medium">{ok ? 'Completed' : 'Failed'}</span>
        <span className="text-muted-foreground">{String(d.step_id ?? '')}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'system.execution.created') {
    const obj = String(d.objective ?? '').slice(0, 80)
    return (
      <div className="flex items-center gap-2 rounded bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        <Play className="h-3 w-3 shrink-0 text-blue-400" />
        <span className="font-medium">Run started</span>
        {obj && <span className="truncate">{obj}</span>}
        <span className="ml-auto shrink-0 text-[10px] tabular-nums">{ts}</span>
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
        'flex items-center gap-2 rounded px-3 py-1.5 text-xs',
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

  return null
}

// ---------------------------------------------------------------------------
// Right panel — artifact cards
// ---------------------------------------------------------------------------

function ArtifactsPanel({ onClose }: { onClose: () => void }) {
  const artifacts = useWorkspaceStore((s) => s.artifacts)
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  const hasContent = streaming || artifacts.length > 0

  return (
    <div className="flex w-[280px] shrink-0 flex-col border-l">
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium">Artifacts</span>
          {streaming && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
              live
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
        {!hasContent ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 py-8">
            <Package className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs text-muted-foreground/70 leading-relaxed">
              Artifacts appear here <strong>while a run is active</strong>.
            </p>
            <p className="text-center text-[11px] text-muted-foreground/50 leading-relaxed max-w-[220px]">
              Post-run artifacts are not yet persisted — see the{' '}
              <strong>Runs</strong> tab for the full agent output of
              completed runs.
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

function ArtifactCard({ artifact }: { artifact: import('@/stores/workspace').ArtifactEntry }) {
  const preview = artifact.content.slice(0, 120)
  const truncated = artifact.content.length > 120

  return (
    <details className="group rounded border border-violet-500/15 bg-violet-500/5 p-2 text-xs">
      <summary className="flex cursor-pointer list-none items-start gap-1.5">
        <Package className="mt-0.5 h-3 w-3 shrink-0 text-violet-400" />
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-snug">{artifact.title}</p>
          <p className="text-[10px] text-muted-foreground/60">
            {shortName(artifact.agentId)} · {artifact.artifactType}
          </p>
        </div>
        <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 border-t border-violet-500/15 pt-2">
        <MarkdownRenderer
          content={truncated ? artifact.content : preview}
          className="text-xs"
        />
      </div>
    </details>
  )
}

// ---------------------------------------------------------------------------
// Drawer conversation (mirrors chat.tsx without URL deps)
// ---------------------------------------------------------------------------

function DrawerConversation({
  sessionId,
  missionId,
}: {
  sessionId: string
  missionId: string
}) {
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
          } catch { /* skip */ }
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
          .map((msg) => <DrawerMessageBubble key={msg.id} message={msg} />)}

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
                  <p className="font-mono text-xs text-muted-foreground whitespace-pre-wrap">
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

function DrawerMessageBubble({ message }: { message: SessionMessage }) {
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
            <p className="mt-2 max-h-48 overflow-y-auto font-mono text-xs text-muted-foreground whitespace-pre-wrap">
              {message.thinking}
            </p>
          </details>
        )}
        {isUser
          ? <p className="text-sm whitespace-pre-wrap">{message.content}</p>
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
// Helpers
// ---------------------------------------------------------------------------

function shortName(agentId: string): string {
  return agentId.endsWith('.agent') ? agentId.slice(0, -6) : agentId
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}
