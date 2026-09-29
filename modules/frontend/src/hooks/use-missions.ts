import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  MissionListItem,
  MissionResponse,
  MissionCreateRequest,
  MissionUpdateRequest,
  MissionCostsResponse,
} from '@/types'

export const missionKeys = {
  all: ['missions'] as const,
  detail: (id: string) => ['missions', id] as const,
  environment: (id: string) => ['missions', id, 'environment'] as const,
  costs: (id: string, tf?: string) => ['missions', id, 'costs', tf ?? 'all'] as const,
}

export function useMissions() {
  return useQuery({
    queryKey: missionKeys.all,
    queryFn: () =>
      api.get<{ missions: MissionListItem[]; total: number }>('/missions'),
    select: (data) => data.missions,
  })
}

export function useMission(id: string | undefined) {
  return useQuery({
    queryKey: missionKeys.detail(id!),
    queryFn: () => api.get<MissionResponse>(`/missions/${id}`),
    enabled: !!id,
  })
}

export function useCreateMission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MissionCreateRequest) =>
      api.post<MissionResponse>('/missions', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useDeleteMission() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api.del(`/missions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export function useUpdateMission(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MissionUpdateRequest) =>
      api.patch<MissionResponse>(`/missions/${id}`, data),
    onSuccess: (updated) => {
      qc.setQueryData(missionKeys.detail(id), updated)
      qc.invalidateQueries({ queryKey: missionKeys.all })
    },
  })
}

export interface EnvironmentInfo {
  id: string
  mode: string
  status: string
  container_name: string | null
  image: string | null
  execution_count: number
  last_execution_at: string | null
  created_at: string
}

export function useMissionEnvironment(id: string | undefined) {
  return useQuery({
    queryKey: missionKeys.environment(id!),
    queryFn: () =>
      api.get<{
        mission_id: string
        active_environment: EnvironmentInfo | null
        all_environments: EnvironmentInfo[]
      }>(`/missions/${id}/environment`),
    enabled: !!id,
    refetchInterval: 15000, // Poll every 15s to track container status
  })
}

export function useMissionCosts(id: string | undefined, timeframe?: string) {
  const params = timeframe ? `?timeframe=${timeframe}` : ''
  return useQuery({
    queryKey: missionKeys.costs(id!, timeframe),
    queryFn: () =>
      api.get<MissionCostsResponse>(`/missions/${id}/costs${params}`),
    enabled: !!id,
  })
}
