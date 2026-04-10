import { create } from 'zustand'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FeedMode = 'chat' | 'plan' | 'narrative' | 'stream' | 'context' | 'runs'

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
  clearLiveTaskOverlay: () => void
  reset: () => void
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const INITIAL = {
  feedMode: 'chat' as FeedMode,
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

  onSseEvent: (eventType, data) => {
    const agentId = String(data.agent_id ?? data.assigned_agent ?? data.agent_name ?? '')

    // ── Live task overlay (Plan 42 §10.9) ─────────────────────────────
    // Transient in-flight status for the Plan tab. The durable truth
    // lives in plan_task_states fetched via GET /plan; this overlay
    // only fills the gap between an SSE event and the next refetch.
    if (eventType === 'plan.step.started') {
      const stepId = String(data.step_id ?? '')
      const nowIso = new Date().toISOString()
      set((s) => ({
        liveTaskOverlay: {
          ...s.liveTaskOverlay,
          [stepId]: { status: 'running', updatedAt: nowIso },
        },
      }))
    }

    else if (eventType === 'plan.step.completed') {
      const stepId = String(data.step_id ?? '')
      const status = String(data.status ?? 'success')
      const overlayStatus: LiveTaskOverlayEntry['status'] =
        status === 'success' ? 'completed' : 'failed'
      const nowIso = new Date().toISOString()
      set((s) => ({
        liveTaskOverlay: {
          ...s.liveTaskOverlay,
          [stepId]: { status: overlayStatus, updatedAt: nowIso },
        },
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
