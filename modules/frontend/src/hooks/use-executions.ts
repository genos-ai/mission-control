import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  ExecutionRecord,
  ExecutionRecordDetail,
  ExecutionDecision,
  ExecutionCostBreakdown,
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
