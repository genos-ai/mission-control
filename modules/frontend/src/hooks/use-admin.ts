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
} from '@/types'

export const adminKeys = {
  catalog: ['admin', 'catalog'] as const,
  metrics: ['admin', 'metrics'] as const,
  costs: ['admin', 'costs'] as const,
  agents: ['admin', 'agents'] as const,
  health: ['admin', 'health'] as const,
  config: ['admin', 'config'] as const,
  users: ['admin', 'users'] as const,
  userKeys: (userId: string) => ['admin', 'users', userId, 'keys'] as const,
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
