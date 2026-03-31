import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface MCDData {
  mission_id: string
  context_data: Record<string, unknown>
  version: number
  size_characters: number
  size_tokens: number
  pct_of_max: number
  max_characters: number
}

export interface ContextChange {
  id: string
  version: number
  change_type: string
  path: string
  old_value: unknown
  new_value: unknown
  agent_id: string | null
  mission_id: string | null
  task_id: string | null
  reason: string
  created_at: string
}

export const contextKeys = {
  mcd: (missionId: string) => ['missions', missionId, 'context'] as const,
  history: (missionId: string) => ['missions', missionId, 'context', 'history'] as const,
}

export function useMCD(missionId: string | undefined) {
  return useQuery({
    queryKey: contextKeys.mcd(missionId!),
    queryFn: () => api.get<MCDData>(`/missions/${missionId}/context`),
    enabled: !!missionId,
  })
}

export function useContextHistory(missionId: string | undefined) {
  return useQuery({
    queryKey: contextKeys.history(missionId!),
    queryFn: () =>
      api.get<{ changes: ContextChange[]; total: number }>(
        `/missions/${missionId}/context/history?limit=30`,
      ),
    select: (data) => data.changes,
    enabled: !!missionId,
  })
}
