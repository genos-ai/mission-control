import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  ExecutionRecord,
  ExecutionRecordDetail,
  ExecutionDecision,
  ExecutionCostBreakdown,
  ExecutionCreateRequest,
  ExecutionCreateResponse,
} from '@/types'

export const executionKeys = {
  all: (filters?: Record<string, string>) =>
    ['executions', filters ?? {}] as const,
  detail: (id: string) => ['executions', id] as const,
  decisions: (id: string) => ['executions', id, 'decisions'] as const,
  cost: (id: string) => ['executions', id, 'cost'] as const,
}

export function useExecutions(filters?: { status?: string; limit?: number; mission_id?: string }) {
  const params = new URLSearchParams()
  if (filters?.status) params.set('status', filters.status)
  if (filters?.limit) params.set('limit', String(filters.limit))
  if (filters?.mission_id) params.set('mission_id', filters.mission_id)
  const qs = params.toString()

  return useQuery({
    queryKey: executionKeys.all(filters as Record<string, string>),
    queryFn: () =>
      api.get<{
        executions: ExecutionRecord[]
        total: number
        page_size: number
        offset: number
      }>(`/executions${qs ? `?${qs}` : ''}`),
    enabled: filters !== undefined,
    // Auto-poll when active tasks exist (Plan 56 Phase D)
    refetchInterval: (query) => {
      const execs = query.state.data?.executions
      if (execs?.some((e) => e.status === 'pending' || e.status === 'running'))
        return 3000
      return false
    },
  })
}

export function useExecution(id: string | undefined) {
  return useQuery({
    queryKey: executionKeys.detail(id!),
    queryFn: () => api.get<ExecutionRecordDetail>(`/executions/${id}`),
    enabled: !!id,
  })
}

export function useExecutionDecisions(id: string | undefined) {
  return useQuery({
    queryKey: executionKeys.decisions(id!),
    queryFn: () =>
      api.get<{ decisions: ExecutionDecision[]; count: number }>(
        `/executions/${id}/decisions`,
      ),
    select: (data) => data.decisions,
    enabled: !!id,
  })
}

export function useExecutionCost(id: string | undefined) {
  return useQuery({
    queryKey: executionKeys.cost(id!),
    queryFn: () =>
      api.get<ExecutionCostBreakdown>(`/executions/${id}/cost`),
    enabled: !!id,
  })
}

/**
 * Background tasks for a mission — execution records with task_type set.
 * Auto-polls every 3s when any task is pending/running.
 */
export function useBackgroundTasks(missionId: string | undefined) {
  const query = useExecutions(missionId ? { mission_id: missionId, limit: 20 } : undefined)

  const tasks = (query.data?.executions ?? []).filter(
    (e) => e.task_type != null,
  )
  const activeTasks = tasks.filter(
    (e) => e.status === 'pending' || e.status === 'running',
  )

  return {
    ...query,
    tasks,
    activeTasks,
    activeCount: activeTasks.length,
  }
}

export function useCreateExecution() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ExecutionCreateRequest) =>
      api.post<ExecutionCreateResponse>('/workflows/missions', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['executions'] })
    },
  })
}

/** Plan 62: unified execution via the plan path. */
export function useRunObjective(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      objective: string
      gate_mode?: string
      budget_ceiling_usd?: number
    }) =>
      api.post<{
        plan_id: string
        outcome_status: string
        workflow_id?: string
      }>(`/missions/${missionId}/plan/run-objective`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['executions'] })
      qc.invalidateQueries({ queryKey: ['plan', missionId] })
    },
  })
}

export function useStartExecution() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (executionId: string) =>
      api.post<ExecutionRecordDetail>(`/executions/${executionId}/execute`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['executions'] })
    },
  })
}

export function useCancelExecution() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (executionId: string) =>
      api.post(`/executions/${executionId}/cancel?reason=Cancelled+by+user`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['executions'] })
    },
  })
}

export function useSubmitApproval() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: {
      executionId: string
      decision: 'approve' | 'reject' | 'retry'
      reason?: string
    }) => {
      const qs = new URLSearchParams({
        decision: params.decision,
        responder_id: 'user:web',
      })
      if (params.reason) qs.set('reason', params.reason)
      return api.post(`/executions/${params.executionId}/submit-approval?${qs}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['executions'] })
    },
  })
}
