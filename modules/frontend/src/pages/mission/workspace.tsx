/**
 * MissionWorkspace — Phase 2
 *
 * Three-panel command center:
 *   Left  (220px) — live agent roster
 *   Center (flex) — Narrative feed | Event stream  (mode toggle)
 *   Right (280px) — artifact cards (collapsed by default)
 *
 * One SSE connection owned here, shared via MissionStreamContext so
 * ConsolePage (Stream mode) doesn't open a second connection.
 *
 * Director Chat slides in as an overlay drawer.
 * CommandBar at the bottom of the center sends directly to the Director.
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
  X,
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
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useTeam } from '@/hooks/use-team'
import { useMissionStream } from '@/hooks/use-sse'
import { useSessions, useMessages, useCreateSession, sessionKeys } from '@/hooks/use-sessions'
import { useAuthStore } from '@/stores/auth'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { useWorkspaceStore } from '@/stores/workspace'
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_CHAT_AGENT = 'mission.director.agent'

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
  const [chatOpen, setChatOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)

  const { data: mission } = useMission(id)
  const updateMission = useUpdateMission(id!)
  const { user } = useAuthStore()
  const isOwner = mission?.owner_id === user?.id

  // ── Single SSE connection, shared via context ──────────────────────────
  const { events: sseEvents, connected } = useMissionStream(id ?? null)

  // Route SSE events into both stores
  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)
  const onSseEvent = useWorkspaceStore((s) => s.onSseEvent)
  const resetWorkspace = useWorkspaceStore((s) => s.reset)
  const resetConsole = useConsoleStore((s) => s.reset)

  // Reset stores on mission change
  const prevMissionId = useRef<string | null>(null)
  useEffect(() => {
    if (id && id !== prevMissionId.current) {
      prevMissionId.current = id
      resetWorkspace()
      resetConsole()
    }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setConnected(connected) }, [connected, setConnected])

  // Forward new SSE events to both stores
  const processedCount = useRef(0)
  useEffect(() => {
    if (sseEvents.length > processedCount.current) {
      const newEvents = sseEvents.slice(processedCount.current)
      processedCount.current = sseEvents.length
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
      })
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
            <Button size="sm" className="h-7 text-xs" onClick={() => setShowRunModal(true)}>
              <Play className="mr-1.5 h-3 w-3" />Run
            </Button>
          </div>
        </div>

        {/* ── Three panels ──────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* Left — live agent roster */}
          <LeftPanel missionId={id!} onChatOpen={() => setChatOpen(true)} />

          {/* Center — Narrative | Stream */}
          <CenterPanel missionId={id!} />

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

        {/* ── Director Chat Drawer ─────────────────────────────────── */}
        {chatOpen && (
          <>
            <div
              className="absolute inset-0 z-40 bg-background/60 backdrop-blur-sm"
              onClick={() => setChatOpen(false)}
            />
            <div className="absolute inset-y-0 right-0 z-50 flex w-[520px] flex-col border-l bg-card shadow-2xl">
              <DirectorChatDrawer missionId={id!} onClose={() => setChatOpen(false)} />
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
  onChatOpen,
}: {
  missionId: string
  onChatOpen: () => void
}) {
  const { data: team, isLoading } = useTeam(missionId)
  const agentStatuses = useWorkspaceStore((s) => s.agentStatuses)

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-r">
      <div className="border-b px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Team
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {isLoading && (
          <div className="flex justify-center py-4"><Spinner className="h-4 w-4" /></div>
        )}
        {team?.map((member) => {
          const agentName = member.agent?.agent_name ?? member.agent_catalog_id
          const live = agentStatuses[agentName]
          return (
            <RosterRow key={member.agent_catalog_id} agentName={agentName} live={live} />
          )
        })}
        {!isLoading && (!team || team.length === 0) && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No agents assigned</p>
        )}
      </div>

      <div className="border-t p-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full h-8 justify-start gap-2 text-xs"
          onClick={onChatOpen}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Director Chat
        </Button>
      </div>
    </div>
  )
}

function RosterRow({
  agentName,
  live,
}: {
  agentName: string
  live?: { status: string; currentTool: string | null }
}) {
  const status = live?.status ?? 'idle'

  const dotColor =
    status === 'running' ? 'bg-amber-400 animate-pulse' :
    status === 'thinking' ? 'bg-purple-400 animate-pulse' :
    status === 'done' ? 'bg-emerald-400' :
    status === 'failed' ? 'bg-destructive' :
    'bg-muted-foreground/30'

  const shortName = agentName.endsWith('.agent')
    ? agentName.slice(0, -6)
    : agentName

  return (
    <div className="flex flex-col px-3 py-1.5">
      <div className="flex items-center gap-2">
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', dotColor)} />
        <span className="truncate text-xs" title={agentName}>{shortName}</span>
      </div>
      {live?.currentTool && (
        <p className="ml-3.5 truncate text-[10px] text-amber-400/80">
          ↳ {live.currentTool}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Center panel — mode toggle + Narrative | Stream
// ---------------------------------------------------------------------------

function CenterPanel({ missionId }: { missionId: string }) {
  const feedMode = useWorkspaceStore((s) => s.feedMode)
  const setFeedMode = useWorkspaceStore((s) => s.setFeedMode)

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l">
      {/* Mode toggle */}
      <div className="flex h-9 shrink-0 items-center gap-1 border-b px-3">
        <div className="flex items-center gap-0.5 rounded-md bg-muted/50 p-0.5">
          {(['narrative', 'stream'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setFeedMode(mode)}
              className={cn(
                'rounded px-3 py-1 text-xs font-medium capitalize transition-colors',
                feedMode === mode
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {feedMode === 'narrative' ? (
          <NarrativeFeed missionId={missionId} />
        ) : (
          <ConsolePage />
        )}
      </div>
    </div>
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

  return (
    <div className="flex w-[280px] shrink-0 flex-col border-l">
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <span className="text-xs font-medium">Artifacts</span>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {artifacts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-4 py-8">
            <Package className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs text-muted-foreground/60">
              Artifacts will appear here as agents produce results.
            </p>
          </div>
        ) : (
          <div className="space-y-px p-2">
            {artifacts.map((a) => (
              <ArtifactCard key={a.id} artifact={a} />
            ))}
          </div>
        )}
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
// Director chat drawer — self-contained, no URL changes
// ---------------------------------------------------------------------------

function DirectorChatDrawer({
  missionId,
  onClose,
}: {
  missionId: string
  onClose: () => void
}) {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const { user } = useAuthStore()

  const { data: sessions, isLoading: loadingSessions } = useSessions({ mission_id: missionId })
  const createSession = useCreateSession()

  useEffect(() => {
    if (!selectedSessionId && sessions && sessions.length > 0) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleNewChat() {
    if (!user) return
    try {
      const session = await createSession.mutateAsync({
        goal: 'Director Chat',
        mission_id: missionId,
        agent_id: DEFAULT_CHAT_AGENT,
      })
      setSelectedSessionId(session.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create session')
    }
  }

  return (
    <>
      <div className="flex h-10 shrink-0 items-center justify-between border-b px-4">
        <span className="text-sm font-medium">Director Chat</span>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <div className="relative flex-1">
          <select
            value={selectedSessionId ?? ''}
            onChange={(e) => setSelectedSessionId(e.target.value || null)}
            className="flex h-7 w-full appearance-none rounded-md border bg-transparent pl-2 pr-7 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">— select thread —</option>
            {sessions?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.goal || s.id.slice(0, 12)} ·{' '}
                {formatDistanceToNow(new Date(s.last_activity_at), { addSuffix: true })}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1.5 h-3.5 w-3.5 text-muted-foreground" />
        </div>
        <Button
          variant="ghost" size="icon" className="h-7 w-7 shrink-0"
          onClick={handleNewChat} disabled={createSession.isPending} title="New thread"
        >
          {createSession.isPending
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Plus className="h-3.5 w-3.5" />}
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {loadingSessions ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : selectedSessionId ? (
          <DrawerConversation sessionId={selectedSessionId} missionId={missionId} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <MessageSquare className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-center text-sm text-muted-foreground">
              Select a thread or start a new conversation.
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
