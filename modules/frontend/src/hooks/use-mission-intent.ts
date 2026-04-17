import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface MissionIntent {
  id: string
  mission_id: string
  intent: string
  intent_summary: string
  scope: Record<string, string[]>
  source: string
  revised_from: string | null
  reason: string
  agent_id: string | null
  session_id: string | null
  created_at: string
}

export const intentKeys = {
  current: (missionId: string) => ['missions', missionId, 'intent'] as const,
  history: (missionId: string) => ['missions', missionId, 'intent', 'history'] as const,
}

export function useCurrentIntent(missionId: string | undefined) {
  return useQuery({
    queryKey: intentKeys.current(missionId!),
    queryFn: () => api.get<MissionIntent | null>(`/missions/${missionId}/intent`),
    enabled: !!missionId,
  })
}

export function useIntentHistory(missionId: string | undefined) {
  return useQuery({
    queryKey: intentKeys.history(missionId!),
    queryFn: () =>
      api.get<{ items: MissionIntent[]; total: number }>(
        `/missions/${missionId}/intent/history?limit=50`,
      ),
    enabled: !!missionId,
  })
}

export function useCreateIntent(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      intent: string
      scope?: Record<string, string[]>
      source: string
      reason: string
    }) => api.post<MissionIntent>(`/missions/${missionId}/intent`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: intentKeys.current(missionId) })
      qc.invalidateQueries({ queryKey: intentKeys.history(missionId) })
    },
  })
}
