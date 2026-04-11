import { create } from 'zustand'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentStatusEntry {
  agentId: string
  status: 'idle' | 'thinking' | 'running' | 'done' | 'failed'
  currentTool: string | null
  lastUpdated: string
}

/**
 * Live in-flight artifact preview, accumulated from
 * `agent.response.chunk` SSE events during an active agent turn.
 * Clears when the agent completes. This is the ONLY ephemeral
 * artifact state left in this store — durable artifacts live in the
 * backend `mission_artifacts` table (Plan 43) and are fetched via
 * `useMissionArtifacts()` in the ArtifactsPanel component.
 */
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
  // Live agent roster
  agentStatuses: Record<string, AgentStatusEntry>

  // Live streaming artifact preview (cleared when the agent completes
  // or when mission.artifact.found fires — the durable row has
  // landed, the streaming preview's job is done).
  streamingArtifact: StreamingArtifact | null

  // Live per-task runtime overlay (Plan 42 §10.9). Populated from
  // plan.step.* SSE events, joined with plan_task_states on the client
  // to render in-flight status without waiting for a refetch.
  liveTaskOverlay: Record<string, LiveTaskOverlayEntry>

  // Actions
  onSseEvent: (eventType: string, data: Record<string, unknown>) => void
  clearLiveTaskOverlay: () => void
  reset: () => void
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const INITIAL = {
  agentStatuses: {} as Record<string, AgentStatusEntry>,
  streamingArtifact: null as StreamingArtifact | null,
  liveTaskOverlay: {} as Record<string, LiveTaskOverlayEntry>,
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  ...INITIAL,

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

    // ── Artifacts panel: live preview lock ─────────────────────────────
    // When a new artifact lands in the backend's mission_artifacts
    // table (mission.artifact.found SSE), clear the streaming preview
    // so the card UI flips from "writing..." to "done". The durable
    // row itself is read via useMissionArtifacts() and invalidated
    // by the layout-level SSE router — this store no longer holds a
    // local copy of the artifact list (Plan 43).
    if (eventType === 'mission.artifact.found') {
      set({ streamingArtifact: null })
    }
  },

  reset: () => set(INITIAL),
}))
