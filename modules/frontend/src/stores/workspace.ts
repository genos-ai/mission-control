import { create } from 'zustand'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FeedMode = 'chat' | 'plan' | 'narrative' | 'stream' | 'context' | 'runs'

export type PlanTaskStatus =
  | 'pending'    // in plan, not yet dispatched
  | 'running'    // dispatch loop executing
  | 'verifying'  // verification pipeline running
  | 'success'    // complete
  | 'failed'     // terminal failure

export interface PlanTask {
  taskId: string
  agentName: string
  description: string
  status: PlanTaskStatus
  orderIndex: number
  costUsd: number
  durationSeconds: number
  currentTool: string | null
  retryCount: number
  resultSummary: string | null
  failureReason: string | null
  artifactEmitted: boolean
}

export interface AgentStatusEntry {
  agentId: string
  status: 'idle' | 'thinking' | 'running' | 'done' | 'failed'
  currentTool: string | null
  lastUpdated: string
}

export interface ArtifactEntry {
  id: string
  agentId: string
  title: string
  content: string
  artifactType: string
  timestamp: string
}

export interface StreamingArtifact {
  agentId: string
  content: string
}

/**
 * Transient per-task runtime overlay, populated from `plan.step.*` SSE
 * events during an active run. Plan 42 §10.9: the Plan tab joins the
 * authoritative plan_task_states (from GET /plan) with this overlay so
 * users see in-flight status changes without waiting for a refetch.
 *
 * Keyed by TaskPlan task_id (string).
 */
export interface LiveTaskOverlayEntry {
  status: 'running' | 'completed' | 'failed'
  updatedAt: string
}

// Task agents excluded from streaming artifact display
const SYSTEM_AGENTS = new Set(['system.planning.agent', 'mission.director.agent'])

// ---------------------------------------------------------------------------
// Store shape
// ---------------------------------------------------------------------------

interface WorkspaceState {
  feedMode: FeedMode

  // Plan board
  planTasks: PlanTask[]
  planningPhase: 'idle' | 'planning' | 'ready' | 'running' | 'complete'

  // Live agent roster
  agentStatuses: Record<string, AgentStatusEntry>

  // Artifacts panel
  artifacts: ArtifactEntry[]
  streamingArtifact: StreamingArtifact | null

  // Live per-task runtime overlay (Plan 42 §10.9). Populated from
  // plan.step.* SSE events, joined with plan_task_states on the client
  // to render in-flight status without waiting for a refetch.
  liveTaskOverlay: Record<string, LiveTaskOverlayEntry>

  // Actions
  setFeedMode: (m: FeedMode) => void
  onSseEvent: (eventType: string, data: Record<string, unknown>) => void
  reorderPlannedTasks: (fromIndex: number, toIndex: number) => void
  clearLiveTaskOverlay: () => void
  reset: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseTasksFromPlan(data: Record<string, unknown>): PlanTask[] {
  const raw = data.tasks ?? data.plan ?? data.task_plan
  if (!Array.isArray(raw)) return []
  return raw.map((t: Record<string, unknown>, i: number) => ({
    taskId: String(t.task_id ?? t.id ?? `task-${i}`),
    agentName: String(t.agent ?? t.agent_name ?? ''),
    description: String(t.description ?? t.task_id ?? ''),
    status: 'pending' as PlanTaskStatus,
    orderIndex: i,
    costUsd: 0,
    durationSeconds: 0,
    currentTool: null,
    retryCount: 0,
    resultSummary: null,
    failureReason: null,
    artifactEmitted: false,
  }))
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const INITIAL = {
  feedMode: 'chat' as FeedMode,
  planTasks: [] as PlanTask[],
  planningPhase: 'idle' as WorkspaceState['planningPhase'],
  agentStatuses: {} as Record<string, AgentStatusEntry>,
  artifacts: [] as ArtifactEntry[],
  streamingArtifact: null as StreamingArtifact | null,
  liveTaskOverlay: {} as Record<string, LiveTaskOverlayEntry>,
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  ...INITIAL,

  setFeedMode: (m) => set({ feedMode: m }),

  clearLiveTaskOverlay: () => set({ liveTaskOverlay: {} }),

  reorderPlannedTasks: (fromIndex, toIndex) =>
    set((s) => {
      const pending = s.planTasks
        .filter((t) => t.status === 'pending')
        .sort((a, b) => a.orderIndex - b.orderIndex)
      const [moved] = pending.splice(fromIndex, 1)
      pending.splice(toIndex, 0, moved)
      // Re-assign orderIndex
      pending.forEach((t, i) => { t.orderIndex = i })
      const rest = s.planTasks.filter((t) => t.status !== 'pending')
      return { planTasks: [...rest, ...pending] }
    }),

  onSseEvent: (eventType, data) => {
    const agentId = String(data.agent_id ?? data.assigned_agent ?? data.agent_name ?? '')

    // ── Plan lifecycle ──────────────────────────────────────────────────
    if (eventType === 'agent.thinking.started' && agentId === 'system.planning.agent') {
      set({ planningPhase: 'planning' })
    }

    else if (eventType === 'plan.created') {
      const tasks = parseTasksFromPlan(data)
      set({ planTasks: tasks, planningPhase: 'ready' })
    }

    else if (eventType === 'system.execution.created') {
      set({ planningPhase: 'running' })
    }

    else if (eventType === 'system.execution.completed') {
      set({ planningPhase: 'complete' })
    }

    // ── Task card state machine ────────────────────────────────────────
    else if (eventType === 'plan.step.started') {
      const stepId = String(data.step_id ?? '')
      const nowIso = new Date().toISOString()
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === stepId ? { ...t, status: 'running', currentTool: null } : t,
        ),
        liveTaskOverlay: {
          ...s.liveTaskOverlay,
          [stepId]: { status: 'running', updatedAt: nowIso },
        },
      }))
    }

    else if (eventType === 'agent.tool.called') {
      const tool = String(data.tool_name ?? '')
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.agentName === agentId && t.status === 'running'
            ? { ...t, currentTool: tool }
            : t,
        ),
      }))
    }

    else if (eventType === 'agent.tool.returned') {
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.agentName === agentId && t.status === 'running'
            ? { ...t, currentTool: null }
            : t,
        ),
      }))
    }

    else if (eventType === 'plan.step.completed') {
      const stepId = String(data.step_id ?? '')
      const status = String(data.status ?? 'success')
      const overlayStatus: LiveTaskOverlayEntry['status'] =
        status === 'success' ? 'completed' : 'failed'
      const nowIso = new Date().toISOString()
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === stepId
            ? { ...t, status: status === 'success' ? 'verifying' : 'failed', currentTool: null }
            : t,
        ),
        liveTaskOverlay: {
          ...s.liveTaskOverlay,
          [stepId]: { status: overlayStatus, updatedAt: nowIso },
        },
      }))
    }

    else if (eventType === 'task.completed') {
      const taskId = String(data.task_id ?? '')
      const cost = data.cost_usd != null ? Number(data.cost_usd) : 0
      const dur = data.duration_seconds != null ? Number(data.duration_seconds) : 0
      const output = data.output_data as Record<string, unknown> | null
      const summary =
        typeof output?.summary === 'string' ? output.summary :
        typeof output?.result === 'string' ? output.result : null
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === taskId
            ? { ...t, status: 'success', costUsd: cost, durationSeconds: dur,
                resultSummary: summary ? summary.slice(0, 200) : null, currentTool: null }
            : t,
        ),
      }))
    }

    else if (eventType === 'task.failed') {
      const taskId = String(data.task_id ?? '')
      const reason = String(data.failure_reason ?? data.error ?? '')
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === taskId
            ? { ...t, status: 'failed', failureReason: reason.slice(0, 200), currentTool: null }
            : t,
        ),
      }))
    }

    else if (eventType === 'task.skipped') {
      const taskId = String(data.task_id ?? '')
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === taskId ? { ...t, status: 'success', resultSummary: 'Skipped' } : t,
        ),
      }))
    }

    else if (eventType === 'mission.artifact.found') {
      // Mark the task that emitted this artifact
      const artifactAgentId = agentId
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.agentName === artifactAgentId ? { ...t, artifactEmitted: true } : t,
        ),
      }))
    }

    // ── Retry tracking ─────────────────────────────────────────────────
    else if (eventType === 'task.attempt.failed') {
      const taskId = String(data.task_id ?? '')
      set((s) => ({
        planTasks: s.planTasks.map((t) =>
          t.taskId === taskId ? { ...t, retryCount: t.retryCount + 1 } : t,
        ),
      }))
    }

    // ── Streaming artifact (right panel live preview) ─────────────────
    if (eventType === 'agent.response.chunk') {
      if (agentId && !SYSTEM_AGENTS.has(agentId)) {
        const chunk = String(data.content ?? '')
        set((s) => ({
          streamingArtifact: {
            agentId,
            content: (s.streamingArtifact?.agentId === agentId
              ? s.streamingArtifact.content
              : '') + chunk,
          },
        }))
      }
    }

    else if (eventType === 'agent.response.complete') {
      if (agentId && !SYSTEM_AGENTS.has(agentId)) {
        set({ streamingArtifact: null })
      }
    }

    // ── Agent roster (reuse for left panel) ───────────────────────────
    if (eventType === 'agent.thinking.started') {
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: { agentId, status: 'thinking', currentTool: null, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    else if (eventType === 'agent.tool.called') {
      if (!agentId) return
      const tool = String(data.tool_name ?? '')
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: { agentId, status: 'running', currentTool: tool, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    else if (eventType === 'agent.tool.returned') {
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: {
            ...s.agentStatuses[agentId],
            agentId, status: 'thinking', currentTool: null, lastUpdated: new Date().toISOString(),
          },
        },
      }))
    }

    else if (eventType === 'agent.response.complete') {
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: { agentId, status: 'done', currentTool: null, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    else if (eventType === 'task.failed') {
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: { agentId, status: 'failed', currentTool: null, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    // ── Artifacts panel ────────────────────────────────────────────────
    if (eventType === 'mission.artifact.found') {
      set({ streamingArtifact: null })   // lock: streaming → completed card
      const entry: ArtifactEntry = {
        id: String(data.event_id ?? crypto.randomUUID()),
        agentId,
        title: String(data.title ?? 'Artifact'),
        content: String(data.content ?? ''),
        artifactType: String(data.artifact_type ?? 'report'),
        timestamp: String(data.timestamp ?? new Date().toISOString()),
      }
      set((s) => ({ artifacts: [entry, ...s.artifacts].slice(0, 50) }))
    }
  },

  reset: () => set(INITIAL),
}))
