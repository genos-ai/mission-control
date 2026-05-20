/**
 * MissionLayout — outer shell for all mission tab routes.
 *
 * Owns the single SSE connection for the mission and fans events into the
 * workspace store (agent statuses, artifacts, live task overlay) and the
 * console store (stream tab). All nine mission tabs are rendered via
 * <Outlet /> in the center content area.
 *
 * The 3-panel chat layout (agent roster + chat + artifacts) lives exclusively
 * inside the Chat tab; all other tabs are full-width content.
 */

import { useState, useRef, useEffect } from 'react'
import { NavLink, Outlet, useParams, Link, useNavigate, useLocation } from 'react-router-dom'
import {
  Activity,
  Users,
  MessageSquare,
  GitBranch,
  Play,
  Terminal,
  FileText,
  Pause,
  Archive,
  RotateCcw,
  Pencil,
  Check,
  X,
  ChevronLeft,
  Settings2,
  Kanban,
  Radio,
  Lightbulb,
  ListChecks,
  Package,
  Loader2,
  DollarSign,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { useMissionStream } from '@/hooks/use-sse'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { useWorkspaceStore } from '@/stores/workspace'
import { planKeys, useMissionPlan, useUpdatePlan } from '@/hooks/use-mission-plan'
import { artifactKeys } from '@/hooks/use-mission-artifacts'
import { queryClient } from '@/lib/query-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { useBackgroundTasks } from '@/hooks/use-executions'
import { RunModal } from '@/components/mission/run-modal'
import { MissionSettingsDrawer } from '@/components/workspace/mission-settings-drawer'
import { MissionStreamContext } from '@/context/mission-stream'
import { useNotificationStore } from '@/stores/notifications'
import { ROUTES } from '@/lib/constants'
import type { MissionStatus } from '@/types'

// ---------------------------------------------------------------------------
// Tab definition
// ---------------------------------------------------------------------------

const tabs = [
  { label: 'Overview',  icon: Activity,      path: 'overview' },
  { label: 'Team',      icon: Users,         path: 'team' },
  { label: 'Chat',      icon: MessageSquare, path: 'chat' },
  { label: 'Plan',      icon: Kanban,        path: 'plan' },
  { label: 'Narrative', icon: Radio,         path: 'narrative' },
  // TODO: Look at collapsing Context and Knowledge tabs together in a
  //       meaningful, intuitive way.
  { label: 'Context',   icon: FileText,      path: 'context' },
  { label: 'Knowledge', icon: Lightbulb,     path: 'knowledge' },
  { label: 'Artifacts', icon: Package,       path: 'artifacts' },
  { label: 'Runs',      icon: ListChecks,    path: 'runs' },
  { label: 'Workflows', icon: GitBranch,     path: 'workflows' },
  { label: 'Costs',     icon: DollarSign,    path: 'costs' },
  { label: 'Console',   icon: Terminal,      path: 'console' },
]

const STATUS_VARIANT: Record<MissionStatus, 'success' | 'warning' | 'secondary'> = {
  active: 'success',
  paused: 'warning',
  archived: 'secondary',
}

function categorize(eventType: string): ConsoleEvent['category'] {
  if (eventType.startsWith('knowledge.')) return 'system'
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
// Layout
// ---------------------------------------------------------------------------

export default function MissionLayout() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: mission, isLoading } = useMission(id)
  const updateMission = useUpdateMission(id!)
  const user = useAuthStore((s) => s.user)
  const isOwner = mission?.owner_id === user?.id

  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)
  const { activeCount: bgTaskCount, activeTasks: bgTasks } = useBackgroundTasks(id)
  const { data: plan } = useMissionPlan(id)
  const updatePlan = useUpdatePlan(id!)

  // Plan is autonomously dispatching if active + gate_mode allows it
  const planIsAutonomous = plan?.status === 'active' &&
    (plan?.gate_mode === 'autonomous' || plan?.gate_mode === 'off')
  const planIsPaused = plan?.status === 'paused'

  async function handlePlanPauseResume() {
    const next = planIsPaused ? 'active' : 'paused'
    try {
      await updatePlan.mutateAsync({ status: next })
      toast.success(next === 'paused' ? 'Plan paused — autonomous dispatch stopped' : 'Plan resumed')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update plan')
    }
  }
  const location = useLocation()

  // Persist last-visited tab per mission for the default-tab redirect
  useEffect(() => {
    if (!id) return
    const segments = location.pathname.split('/')
    const tabIdx = segments.indexOf(id) + 1
    const tab = segments[tabIdx]
    if (tab && !tab.includes(':')) {
      localStorage.setItem(`missions.lastTab.${id}`, tab)
    }
  }, [location.pathname, id])

  // ── Single SSE connection, shared via MissionStreamContext ────────────────
  const { events: sseEvents, connected, totalAdded } = useMissionStream(id ?? null)

  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)
  const onSseEvent = useWorkspaceStore((s) => s.onSseEvent)
  const resetWorkspace = useWorkspaceStore((s) => s.reset)
  const resetConsole = useConsoleStore((s) => s.reset)
  const addNotification = useNotificationStore((s) => s.add)

  // Tracks how many SSE events have been fanned into stores.
  // Declared here so the mission-change reset below can access it.
  const processedTotal = useRef(0)

  // Reset stores on mission change
  const prevMissionId = useRef<string | null>(null)
  useEffect(() => {
    if (id && id !== prevMissionId.current) {
      prevMissionId.current = id
      processedTotal.current = 0
      resetWorkspace()
      resetConsole()
    }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setConnected(connected) }, [connected, setConnected])

  // Forward SSE events into workspace + console stores.
  // Uses totalAdded (not sseEvents.length) as the effect trigger so new events
  // are never missed when the ring buffer is full and length stays at 1000.
  useEffect(() => {
    if (totalAdded <= processedTotal.current) return
    const delta = totalAdded - processedTotal.current
    // Take the last `delta` events from the ring buffer — they are always
    // the newest since useFetchSse only appends (then slices the tail).
    const newEvents = sseEvents.slice(-delta)
    processedTotal.current = totalAdded
    let planInvalidated = false
    let artifactsInvalidated = false
    newEvents.forEach((ev) => {
      const top = ev.data as Record<string, unknown>
      const d = (top.data ?? top) as Record<string, unknown>
      onSseEvent(ev.event_type, d)
      addEvent({
        event_id: String(top.event_id ?? d.event_id ?? crypto.randomUUID()),
        event_type: ev.event_type,
        category: categorize(ev.event_type),
        timestamp: String(top.timestamp ?? d.timestamp ?? new Date().toISOString()),
        source: String(d.agent_id ?? top.source ?? d.source ?? ''),
        data: d,
      })
      if (ev.event_type.startsWith('mission_plan.') && id) {
        planInvalidated = true
      }
      // Plan 43: mission.artifact.found means a new artifact has
      // (or will shortly) land in mission_artifacts. Coalesce to a
      // single invalidation per batch to avoid storms.
      if (ev.event_type === 'mission.artifact.found' && id) {
        artifactsInvalidated = true
      }
      // Notify the user when a workflow step is waiting for their input.
      // This surfaces even if they navigate away from the workflow editor.
      if (ev.event_type === 'workflow.human_input.requested' && id) {
        addNotification({
          id: String(d.request_id ?? crypto.randomUUID()),
          type: 'human_input_needed',
          title: 'Workflow awaiting your input',
          body: String(d.prompt_message ?? 'A workflow step requires your decision.'),
          mission_id: id,
          data: {
            request_id: d.request_id,
            step_id: d.step_id,
            workflow_run_id: d.workflow_run_id,
          },
          read: false,
          created_at: new Date().toISOString(),
        })
      }
    })
    if (planInvalidated && id) {
      queryClient.invalidateQueries({ queryKey: planKeys.plan(id) })
    }
    if (artifactsInvalidated && id) {
      queryClient.invalidateQueries({ queryKey: artifactKeys.list(id) })
    }
    // Plan 56 Phase D: invalidate execution queries when background
    // tasks complete, so the header indicator updates immediately
    if (newEvents.some((ev) =>
      ev.event_type === 'system.info' || ev.event_type === 'execution.record'
    ) && id) {
      queryClient.invalidateQueries({ queryKey: ['executions'] })
    }
    // Plan 56: When a Director followup (ChatTurnWorkflow) completes,
    // its agent.response.complete event arrives via the mission SSE stream.
    // Invalidate session messages so the chat tab picks it up without refresh.
    if (newEvents.some((ev) => ev.event_type === 'agent.response.complete' || ev.event_type === 'user.message.sent')) {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }
  }, [totalAdded]) // eslint-disable-line react-hooks/exhaustive-deps

  function setStatus(status: MissionStatus) {
    updateMission.mutate({ status })
  }

  const streamValue = { events: sseEvents, connected }

  return (
    <MissionStreamContext.Provider value={streamValue}>
      <div className="relative flex h-full flex-col">

        {/* ── Mission header ─────────────────────────────────────────── */}
        <div className="flex items-start justify-between border-b px-6 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              <Link
                to={ROUTES.DASHBOARD}
                className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                title="Back to dashboard"
              >
                <ChevronLeft className="h-4 w-4" />
              </Link>
              {isLoading ? (
                <Spinner className="h-5 w-5" />
              ) : mission ? (
                <>
                  <h1 className="truncate text-lg font-bold">{mission.name}</h1>
                  {mission.tier === 'platform' && (
                    <Badge variant="outline" className="border-amber-500 text-[10px] text-amber-600">
                      platform
                    </Badge>
                  )}
                  <Badge variant={STATUS_VARIANT[mission.status as MissionStatus]}>
                    {mission.status}
                  </Badge>
                </>
              ) : (
                <p className="text-muted-foreground">Mission not found</p>
              )}
            </div>
            {mission && (
              <InlineBrief brief={mission.brief} missionId={id!} editable={isOwner} />
            )}
          </div>

          <div className="ml-4 flex shrink-0 items-center gap-2">
            {isOwner && mission && (
              <>
                {mission.status === 'active' && (
                  <Button variant="outline" size="sm" onClick={() => setStatus('paused')}>
                    <Pause className="mr-1.5 h-3.5 w-3.5" />Pause
                  </Button>
                )}
                {mission.status === 'paused' && (
                  <Button variant="outline" size="sm" onClick={() => setStatus('active')}>
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" />Resume
                  </Button>
                )}
                {mission.status !== 'archived' && (
                  <Button variant="outline" size="sm" onClick={() => setStatus('archived')}>
                    <Archive className="mr-1.5 h-3.5 w-3.5" />Archive
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
            {bgTaskCount > 0 && (
              <div
                className="flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1 text-[11px] text-primary"
                title={bgTasks.map((t) => `${t.task_type}: ${t.status}`).join('\n')}
              >
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>{bgTaskCount} background {bgTaskCount === 1 ? 'task' : 'tasks'}</span>
              </div>
            )}
            {(planIsAutonomous || planIsPaused) && (
              <Button
                size="sm"
                variant={planIsPaused ? 'outline' : 'destructive'}
                onClick={handlePlanPauseResume}
                disabled={updatePlan.isPending}
              >
                {planIsPaused ? (
                  <><RotateCcw className="mr-1.5 h-3.5 w-3.5" />Resume Plan</>
                ) : (
                  <><Pause className="mr-1.5 h-3.5 w-3.5" />Stop Plan</>
                )}
              </Button>
            )}
            <Button size="sm" onClick={() => setShowRunModal(true)}>
              <Play className="mr-1.5 h-3.5 w-3.5" />Run
            </Button>
          </div>
        </div>

        {/* ── Tab bar ────────────────────────────────────────────────── */}
        <div className="flex border-b px-4">
          {tabs.map((tab) => (
            <NavLink
              key={tab.path}
              to={`/missions/${id}/${tab.path}`}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                  isActive
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground',
                )
              }
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </NavLink>
          ))}
        </div>

        {/* ── Tab content ────────────────────────────────────────────── */}
        {/* min-h-0 + overflow-y-auto so full-page tabs scroll normally.    */}
        {/* Chat tab opts into h-full to fill this bounded container.       */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>

        {/* ── Mission Settings Drawer ─────────────────────────────────── */}
        {settingsOpen && (
          <>
            <div
              className="absolute inset-0 z-40 bg-background/60 backdrop-blur-sm"
              onClick={() => setSettingsOpen(false)}
            />
            <div className="absolute inset-y-0 right-0 z-50 flex w-[480px] flex-col border-l bg-card shadow-2xl">
              <MissionSettingsDrawer missionId={id!} onClose={() => setSettingsOpen(false)} />
            </div>
          </>
        )}

        {showRunModal && id && (
          <RunModal
            missionId={id}
            onClose={() => setShowRunModal(false)}
            onStarted={() => {
              setShowRunModal(false)
              navigate(ROUTES.MISSION_PLAN(id!))
            }}
          />
        )}
      </div>
    </MissionStreamContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Inline brief editor (shown below mission name in the header)
// ---------------------------------------------------------------------------

function InlineBrief({
  brief,
  missionId,
  editable,
}: {
  brief: string | null
  missionId: string
  editable: boolean
}) {
  const updateMission = useUpdateMission(missionId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(brief ?? '')

  const save = () => {
    const value = draft.trim()
    updateMission.mutate(
      { brief: value || undefined },
      {
        onSuccess: () => {
          setEditing(false)
          toast.success('Brief updated')
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  if (editing) {
    return (
      <div className="ml-7 mt-1 flex items-center gap-2">
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') {
              setEditing(false)
              setDraft(brief ?? '')
            }
          }}
          className="flex-1 rounded-md border bg-transparent px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Set mission objective / brief..."
        />
        <Button
          variant="ghost" size="icon" className="h-7 w-7"
          onClick={save} disabled={updateMission.isPending}
        >
          <Check className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost" size="icon" className="h-7 w-7"
          onClick={() => { setEditing(false); setDraft(brief ?? '') }}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
    )
  }

  if (!brief && editable) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="ml-7 mt-1 flex items-center gap-1.5 text-sm text-muted-foreground/60 transition-colors hover:text-muted-foreground"
      >
        <Pencil className="h-3 w-3" />
        <span className="italic">Set mission brief...</span>
      </button>
    )
  }

  return (
    <button
      onClick={() => editable && setEditing(true)}
      className={cn(
        'ml-7 mt-1 flex items-center gap-1.5 text-sm text-muted-foreground group',
        editable && 'cursor-pointer hover:text-foreground',
      )}
    >
      <span className="line-clamp-1">{brief}</span>
      {editable && (
        <Pencil className="h-3 w-3 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </button>
  )
}
