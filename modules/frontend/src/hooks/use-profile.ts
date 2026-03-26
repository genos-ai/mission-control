import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ApiKeyResponse, ApiKeyCreateResponse } from '@/types'

const profileKeys = {
  apiKeys: ['profile', 'api-keys'] as const,
}

export function useOwnApiKeys() {
  return useQuery({
    queryKey: profileKeys.apiKeys,
    queryFn: () => api.get<ApiKeyResponse[]>('/auth/api-keys'),
  })
}

export function useCreateOwnApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; expires_in_days?: number }) =>
      api.post<ApiKeyCreateResponse>('/auth/api-keys', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: profileKeys.apiKeys })
    },
  })
}

export function useRevokeOwnApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) => api.del(`/auth/api-keys/${keyId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: profileKeys.apiKeys })
    },
  })
}
