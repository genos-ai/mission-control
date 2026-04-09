import { create } from 'zustand'

export type FeedMode = 'narrative' | 'stream'

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

interface WorkspaceState {
  feedMode: FeedMode
  agentStatuses: Record<string, AgentStatusEntry>
  artifacts: ArtifactEntry[]

  setFeedMode: (m: FeedMode) => void
  onSseEvent: (eventType: string, data: Record<string, unknown>) => void
  reset: () => void
}

const INITIAL: Pick<WorkspaceState, 'feedMode' | 'agentStatuses' | 'artifacts'> = {
  feedMode: 'narrative',
  agentStatuses: {},
  artifacts: [],
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  ...INITIAL,

  setFeedMode: (m) => set({ feedMode: m }),

  onSseEvent: (eventType, data) => {
    const agentId = String(data.agent_id ?? data.assigned_agent ?? '')

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
            agentId,
            status: 'thinking',
            currentTool: null,
            lastUpdated: new Date().toISOString(),
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

    else if (eventType === 'plan.step.started') {
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: { agentId, status: 'thinking', currentTool: null, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    else if (eventType === 'plan.step.completed') {
      const status = String(data.status ?? 'done')
      if (!agentId) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [agentId]: {
            agentId,
            status: status === 'success' ? 'done' : 'failed',
            currentTool: null,
            lastUpdated: new Date().toISOString(),
          },
        },
      }))
    }

    else if (eventType === 'task.failed') {
      const name = String(data.agent_name ?? agentId)
      if (!name) return
      set((s) => ({
        agentStatuses: {
          ...s.agentStatuses,
          [name]: { agentId: name, status: 'failed', currentTool: null, lastUpdated: new Date().toISOString() },
        },
      }))
    }

    else if (eventType === 'mission.artifact.found') {
      const entry: ArtifactEntry = {
        id: String(data.event_id ?? crypto.randomUUID()),
        agentId: agentId,
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
