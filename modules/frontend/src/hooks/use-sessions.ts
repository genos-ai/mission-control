import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  SessionListItem,
  SessionResponse,
  SessionCreateRequest,
  SessionMessage,
} from '@/types'

export const sessionKeys = {
  all: (filters?: Record<string, string>) =>
    ['sessions', filters ?? {}] as const,
  detail: (id: string) => ['sessions', id] as const,
  messages: (id: string, senderId?: string) => ['sessions', id, 'messages', senderId ?? 'all'] as const,
}

export function useSessions(filters?: { user_id?: string; mission_id?: string; status?: string }) {
  const params = new URLSearchParams()
  if (filters?.user_id) params.set('user_id', filters.user_id)
  if (filters?.mission_id) params.set('mission_id', filters.mission_id)
  if (filters?.status) params.set('status', filters.status)
  const qs = params.toString()

  return useQuery({
    queryKey: sessionKeys.all(filters as Record<string, string>),
    queryFn: () =>
      api.get<SessionListItem[]>(`/sessions${qs ? `?${qs}` : ''}`),
  })
}

export function useSession(id: string | undefined) {
  return useQuery({
    queryKey: sessionKeys.detail(id!),
    queryFn: () => api.get<SessionResponse>(`/sessions/${id}`),
    enabled: !!id,
  })
}

export function useMessages(sessionId: string | undefined, senderId?: string) {
  const params = new URLSearchParams({ limit: '200' })
  if (senderId) params.set('sender_id', senderId)

  return useQuery({
    queryKey: sessionKeys.messages(sessionId!, senderId),
    queryFn: () =>
      api.get<SessionMessage[]>(`/sessions/${sessionId}/messages?${params}`),
    enabled: !!sessionId,
    // Poll every 2s when any message is still streaming (Plan 56 Phase A).
    // Stops polling once all messages are complete or failed.
    refetchInterval: (query) => {
      const data = query.state.data
      if (data?.some((m) => m.status === 'streaming')) return 2000
      return false
    },
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SessionCreateRequest) =>
      api.post<SessionResponse>('/sessions', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}

export function useCompleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<SessionResponse>(`/sessions/${sessionId}/complete`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}
