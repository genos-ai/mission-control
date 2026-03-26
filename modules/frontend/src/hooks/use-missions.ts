import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  MissionListItem,
  MissionResponse,
  MissionCreateRequest,
  MissionUpdateRequest,
} from '@/types'

export const missionKeys = {
  all: ['missions'] as const,
  detail: (id: string) => ['missions', id] as const,
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
