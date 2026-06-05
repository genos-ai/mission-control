import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  AgentCatalogItem,
  AgentCatalogDetail,
  UserResponse,
  AdminMetricsOverview,
  AdminCostBreakdown,
  AdminAgentStats,
  HealthCheck,
  ApiKeyResponse,
  ApiKeyCreateResponse,
  TokenBreakdown,
  TokenEconomicsSummary,
  CachePerformance,
  CostTimelinePoint,
  ExpensiveCall,
  ModelDistribution,
  OutputEfficiency,
} from '@/types'

export const adminKeys = {
  catalog: ['admin', 'catalog'] as const,
  models: ['admin', 'models'] as const,
  metrics: ['admin', 'metrics'] as const,
  costs: ['admin', 'costs'] as const,
  agents: ['admin', 'agents'] as const,
  health: ['admin', 'health'] as const,
  config: ['admin', 'config'] as const,
  users: ['admin', 'users'] as const,
  userKeys: (userId: string) => ['admin', 'users', userId, 'keys'] as const,
  tokenEconomics: (tf: string) => ['admin', 'token-economics', tf] as const,
  cachePerformance: (tf: string) => ['admin', 'cache-performance', tf] as const,
  costTimeline: (tf: string, g: string) => ['admin', 'cost-timeline', tf, g] as const,
  expensiveCalls: (tf: string) => ['admin', 'expensive-calls', tf] as const,
  modelDistribution: (tf: string) => ['admin', 'model-distribution', tf] as const,
  outputEfficiency: (tf: string) => ['admin', 'output-efficiency', tf] as const,
}

// --- Catalog ---

export function useAdminCatalog() {
  return useQuery({
    queryKey: adminKeys.catalog,
    queryFn: () =>
      api.get<{ agents: AgentCatalogItem[]; count: number }>(
        '/admin/catalog',
      ),
    select: (data) => data.agents,
  })
}

/** Valid provider → models registry for the model picker. */
export function useAdminModels() {
  return useQuery({
    queryKey: adminKeys.models,
    queryFn: () =>
      api.get<{ models: Record<string, string[]> }>('/admin/models'),
    select: (data) => data.models,
    staleTime: 5 * 60 * 1000,
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<AgentCatalogDetail>) =>
      api.post('/admin/catalog', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.catalog })
    },
  })
}

export function useUpdateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentName,
      data,
    }: {
      agentName: string
      data: Partial<AgentCatalogDetail>
    }) => api.patch(`/admin/catalog/${agentName}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.catalog })
    },
  })
}

export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (agentName: string) =>
      api.del(`/admin/catalog/${agentName}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.catalog })
    },
  })
}

export function useUpdateSystemPrompt() {
  return useMutation({
    mutationFn: ({
      agentName,
      content,
      changedBy,
      changeReason,
    }: {
      agentName: string
      content: string
      changedBy: string
      changeReason?: string
    }) =>
      api.put(`/admin/catalog/${agentName}/prompt`, {
        content,
        changed_by: changedBy,
        change_reason: changeReason,
      }),
  })
}

export function useSeedCatalog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/admin/seed-catalog'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.catalog })
    },
  })
}

// --- Metrics ---

export function useMetricsOverview() {
  return useQuery({
    queryKey: adminKeys.metrics,
    queryFn: () => api.get<AdminMetricsOverview>('/admin/metrics/overview'),
  })
}

export function useMetricsCosts() {
  return useQuery({
    queryKey: adminKeys.costs,
    queryFn: () => api.get<AdminCostBreakdown>('/admin/metrics/costs'),
  })
}

export function useMetricsAgents() {
  return useQuery({
    queryKey: adminKeys.agents,
    queryFn: () =>
      api.get<{ agents: AdminAgentStats[] }>('/admin/metrics/agents'),
    select: (data) => data.agents,
  })
}

// --- System ---

export function useHealthCheck() {
  return useQuery({
    queryKey: adminKeys.health,
    queryFn: () => api.get<HealthCheck>('/admin/system/health'),
    refetchInterval: 30_000,
  })
}

export function useAdminConfig() {
  return useQuery({
    queryKey: adminKeys.config,
    queryFn: () => api.get<Record<string, unknown>>('/admin/config'),
  })
}

// --- Emergency Stop (Plan 51 Phase C) ---

export interface EmergencyStopResult {
  paused_count: number
  message: string
}

export function useEmergencyStop() {
  return useMutation({
    mutationFn: () =>
      api.post<EmergencyStopResult>('/admin/dispatch/emergency-stop'),
  })
}

// --- Token Economics (Plan 60) ---

export function useTokenBreakdown(timeframe = '7d') {
  return useQuery({
    queryKey: adminKeys.tokenEconomics(timeframe),
    queryFn: () =>
      api.get<{ agents: TokenBreakdown[]; summary: TokenEconomicsSummary }>(
        `/admin/metrics/token-economics?timeframe=${timeframe}`,
      ),
  })
}

export function useCachePerformance(timeframe = '7d') {
  return useQuery({
    queryKey: adminKeys.cachePerformance(timeframe),
    queryFn: () =>
      api.get<{ agents: CachePerformance[] }>(
        `/admin/metrics/cache-performance?timeframe=${timeframe}`,
      ),
    select: (data) => data.agents,
  })
}

export function useCostTimeline(timeframe = '7d', groupBy = 'agent') {
  return useQuery({
    queryKey: adminKeys.costTimeline(timeframe, groupBy),
    queryFn: () =>
      api.get<{ timeline: CostTimelinePoint[] }>(
        `/admin/metrics/cost-timeline?timeframe=${timeframe}&group_by=${groupBy}`,
      ),
    select: (data) => data.timeline,
  })
}

export function useExpensiveCalls(timeframe = '7d') {
  return useQuery({
    queryKey: adminKeys.expensiveCalls(timeframe),
    queryFn: () =>
      api.get<{ calls: ExpensiveCall[] }>(
        `/admin/metrics/expensive-calls?timeframe=${timeframe}`,
      ),
    select: (data) => data.calls,
  })
}

export function useModelDistribution(timeframe = '7d') {
  return useQuery({
    queryKey: adminKeys.modelDistribution(timeframe),
    queryFn: () =>
      api.get<{ models: ModelDistribution[] }>(
        `/admin/metrics/model-distribution?timeframe=${timeframe}`,
      ),
    select: (data) => data.models,
  })
}

export function useOutputEfficiency(timeframe = '7d') {
  return useQuery({
    queryKey: adminKeys.outputEfficiency(timeframe),
    queryFn: () =>
      api.get<{ agents: OutputEfficiency[] }>(
        `/admin/metrics/output-efficiency?timeframe=${timeframe}`,
      ),
    select: (data) => data.agents,
  })
}

// --- Users ---

export function useAdminUsers() {
  return useQuery({
    queryKey: adminKeys.users,
    queryFn: () => api.get<UserResponse[]>('/admin/users'),
  })
}

export function useCreateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      email: string
      password: string
      display_name: string
      system_role?: string
    }) => api.post<UserResponse>('/admin/users', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

export function useUpdateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      userId,
      data,
    }: {
      userId: string
      data: { display_name?: string; system_role?: string; is_active?: boolean }
    }) => api.patch<UserResponse>(`/admin/users/${userId}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

export function useDeactivateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.del(`/admin/users/${userId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.users })
    },
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({
      userId,
      newPassword,
    }: {
      userId: string
      newPassword: string
    }) =>
      api.post(`/admin/users/${userId}/reset-password`, {
        new_password: newPassword,
      }),
  })
}

export function useUserApiKeys(userId: string | undefined) {
  return useQuery({
    queryKey: adminKeys.userKeys(userId!),
    queryFn: () =>
      api.get<ApiKeyResponse[]>(`/admin/users/${userId}/api-keys`),
    enabled: !!userId,
  })
}

export function useCreateApiKey(userId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; expires_in_days?: number }) =>
      api.post<ApiKeyCreateResponse>(
        `/admin/users/${userId}/api-keys`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.userKeys(userId) })
    },
  })
}

export function useRevokeApiKey(userId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      api.del(`/admin/users/${userId}/api-keys/${keyId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.userKeys(userId) })
    },
  })
}
