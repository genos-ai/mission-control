import { create } from 'zustand'

export interface TaskResult {
  stepId: string
  agent: string
  status: string
  costUsd: number
  durationSeconds: number
  summary: string
}

interface PendingApproval {
  executionId: string
  message: string
}

interface SseEvent {
  event_type: string
  data: Record<string, unknown>
}

interface LiveRunState {
  // Identity
  executionId: string | null
  sessionId: string | null

  // Phase
  phase: 'planning' | 'executing' | 'done'
  status: 'planning' | 'running' | 'success' | 'failed'

  // Left panel: live activity
  activeAgents: Map<string, string>
  thinkingBuffers: Map<string, string>
  planningSteps: { step: string; message: string }[]
  eventLog: SseEvent[]

  // Right panel: results
  taskResults: TaskResult[]
  errors: string[]

  // Footer
  totalCost: number
  totalTasks: number
  completedTasks: number
  startedAt: number | null

  // Gate
  pendingApproval: PendingApproval | null

  // Internal cross-reference maps
  _stepAgents: Map<string, string>
  _agentCosts: Map<string, number>
  _agentStart: Map<string, number>

  // Actions
  init: (executionId: string, sessionId: string) => void
  handleEvent: (event: SseEvent) => void
  setDone: (status: 'success' | 'failed') => void
  reset: () => void
}

const INITIAL_STATE = {
  executionId: null,
  sessionId: null,
  phase: 'planning' as const,
  status: 'planning' as const,
  activeAgents: new Map<string, string>(),
  thinkingBuffers: new Map<string, string>(),
  planningSteps: [] as { step: string; message: string }[],
  eventLog: [] as SseEvent[],
  taskResults: [] as TaskResult[],
  errors: [] as string[],
  totalCost: 0,
  totalTasks: 0,
  completedTasks: 0,
  startedAt: null as number | null,
  pendingApproval: null as PendingApproval | null,
  _stepAgents: new Map<string, string>(),
  _agentCosts: new Map<string, number>(),
  _agentStart: new Map<string, number>(),
}

export const useLiveRunStore = create<LiveRunState>((set, get) => ({
  ...INITIAL_STATE,

  init: (executionId, sessionId) =>
    set({ ...INITIAL_STATE, executionId, sessionId, startedAt: Date.now() }),

  reset: () => set(INITIAL_STATE),

  setDone: (status) => set({ phase: 'done', status }),

  handleEvent: (event) => {
    const state = get()
    const etype = event.event_type
    const d = event.data ?? event

    switch (etype) {
      case 'plan.phase': {
        const step = String(d.step ?? '')
        const message = String(d.message ?? '')
        set({
          planningSteps: [...state.planningSteps, { step, message }],
        })
        return
      }

      case 'plan.created': {
        const tasks = (d.tasks as unknown[]) ?? []
        set({
          phase: 'executing',
          status: 'running',
          totalTasks: tasks.length || state.totalTasks,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'plan.step.started': {
        const stepId = String(d.step_id ?? '')
        const agent = String(d.assigned_agent ?? '')
        const newStepAgents = new Map(state._stepAgents)
        const newAgentStart = new Map(state._agentStart)
        const newActive = new Map(state.activeAgents)
        if (stepId && agent) {
          newStepAgents.set(stepId, agent)
          newAgentStart.set(agent, Date.now())
          newActive.set(agent, 'executing')
        }
        set({
          _stepAgents: newStepAgents,
          _agentStart: newAgentStart,
          activeAgents: newActive,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'plan.step.completed': {
        const stepId = String(d.step_id ?? '?')
        const taskStatus = String(d.status ?? '?')
        const summary = String(d.result_summary ?? '')
        const agent = state._stepAgents.get(stepId) ?? ''
        const cost = state._agentCosts.get(agent) ?? 0
        const startTime = state._agentStart.get(agent) ?? 0
        const duration = startTime ? (Date.now() - startTime) / 1000 : 0

        const result: TaskResult = {
          stepId,
          agent,
          status: taskStatus,
          costUsd: cost,
          durationSeconds: duration,
          summary,
        }

        const newActive = new Map(state.activeAgents)
        if (agent) newActive.delete(agent)

        const errors =
          taskStatus === 'failed' && summary
            ? [...state.errors, `${stepId}: ${summary}`]
            : state.errors

        set({
          taskResults: [...state.taskResults, result],
          completedTasks: state.completedTasks + 1,
          activeAgents: newActive,
          errors,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'agent.thinking.started': {
        const agentId = String(d.agent_id ?? '')
        if (!agentId) return
        const newActive = new Map(state.activeAgents)
        const newBuffers = new Map(state.thinkingBuffers)
        newActive.set(agentId, 'thinking')
        newBuffers.set(agentId, '')
        set({
          activeAgents: newActive,
          thinkingBuffers: newBuffers,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'agent.tool.called': {
        const agentId = String(d.agent_id ?? '')
        const toolName = String(d.tool_name ?? '')
        if (!agentId) break
        const newActive = new Map(state.activeAgents)
        newActive.set(agentId, `tool: ${toolName}`)
        set({
          activeAgents: newActive,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'agent.tool.returned': {
        const agentId = String(d.agent_id ?? '')
        if (!agentId) break
        const newActive = new Map(state.activeAgents)
        if (newActive.has(agentId)) {
          newActive.set(agentId, 'executing')
        }
        set({
          activeAgents: newActive,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'agent.response.chunk': {
        const agentId = String(d.agent_id ?? '')
        const chunk = String(d.chunk ?? '')
        if (!agentId) return
        const newBuffers = new Map(state.thinkingBuffers)
        const prev = newBuffers.get(agentId) ?? ''
        newBuffers.set(agentId, (prev + chunk).slice(-2000))
        set({ thinkingBuffers: newBuffers })
        // Don't add chunks to eventLog — too noisy
        return
      }

      case 'agent.response.complete': {
        const agentId = String(d.agent_id ?? '')
        const cost = Number(d.cost_usd ?? 0)
        const metadata = (d.metadata ?? {}) as Record<string, unknown>
        const isError = metadata.error === true
        const newActive = new Map(state.activeAgents)
        const newBuffers = new Map(state.thinkingBuffers)
        const newCosts = new Map(state._agentCosts)
        newActive.delete(agentId)
        newBuffers.delete(agentId)
        newCosts.set(agentId, (newCosts.get(agentId) ?? 0) + cost)

        const errors = isError
          ? [...state.errors, `${agentId}: ${String(d.full_content ?? 'unknown error')}`]
          : state.errors

        set({
          activeAgents: newActive,
          thinkingBuffers: newBuffers,
          _agentCosts: newCosts,
          errors,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'session.cost.updated': {
        set({ totalCost: Number(d.cost_usd ?? state.totalCost) })
        return
      }

      case 'agent.approval.requested': {
        set({
          pendingApproval: {
            executionId: state.executionId ?? '',
            message: String(d.message ?? 'Approval required'),
          },
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      case 'agent.approval.response': {
        set({
          pendingApproval: null,
          eventLog: [...state.eventLog, event].slice(-100),
        })
        return
      }

      default: {
        // All other events go to event log
        set({ eventLog: [...state.eventLog, event].slice(-100) })
      }
    }
  },
}))
