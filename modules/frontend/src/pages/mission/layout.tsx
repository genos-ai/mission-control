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
import { Outlet, useParams, useNavigate, useLocation } from 'react-router-dom'
import { useMissionStream } from '@/hooks/use-sse'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { useWorkspaceStore } from '@/stores/workspace'
import { planKeys } from '@/hooks/use-mission-plan'
import { artifactKeys } from '@/hooks/use-mission-artifacts'
import { queryClient } from '@/lib/query-client'
import { RunModal } from '@/components/mission/run-modal'
import { MissionTopBar } from '@/components/mission/mission-top-bar'
import { MissionSettingsDrawer } from '@/components/workspace/mission-settings-drawer'
import { MissionStreamContext } from '@/context/mission-stream'
import { useNotificationStore } from '@/stores/notifications'
import { ROUTES } from '@/lib/constants'

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

  const [settingsOpen, setSettingsOpen] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)
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

  // Reconnect catch-up: SSE drops between events stop pushing invalidations,
  // so on a real reconnect (false → true on the same mission), refetch the
  // queries that the per-event SSE handler would normally keep fresh. Skips
  // the initial mount (when no previous connection on this mission existed).
  const lastConnectedMission = useRef<string | null>(null)
  useEffect(() => {
    if (!id || !connected) return
    const wasReconnect = lastConnectedMission.current === id
    lastConnectedMission.current = id
    if (wasReconnect) {
      queryClient.invalidateQueries({ queryKey: planKeys.plan(id) })
      queryClient.invalidateQueries({ queryKey: artifactKeys.list(id) })
      queryClient.invalidateQueries({ queryKey: ['executions'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }
  }, [connected, id])

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

  const streamValue = { events: sseEvents, connected }

  return (
    <MissionStreamContext.Provider value={streamValue}>
      <div className="relative flex h-full flex-col">

        <MissionTopBar
          missionId={id!}
          onOpenSettings={() => setSettingsOpen(true)}
          onRun={() => setShowRunModal(true)}
        />

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
            <div className="absolute inset-y-0 right-0 z-50 flex w-[480px] flex-col rounded-l-panel border-l border-panel-border bg-panel shadow-2xl">
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
