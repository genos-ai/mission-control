/**
 * Mission schedule hooks (Plan 88). The api client unwraps the ApiResponse
 * envelope; every mutation invalidates ['mission-schedules', missionId].
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  MissionScheduleCreate,
  MissionScheduleResponse,
  MissionScheduleUpdate,
} from '@/types'

export const missionScheduleKeys = {
  all: (missionId: string) => ['mission-schedules', missionId] as const,
  list: (missionId: string, includeArchived: boolean) =>
    ['mission-schedules', missionId, 'list', includeArchived] as const,
  detail: (missionId: string, scheduleId: string) =>
    ['mission-schedules', missionId, 'detail', scheduleId] as const,
}

export function useMissionSchedules(missionId: string | undefined, includeArchived: boolean) {
  return useQuery({
    queryKey: missionScheduleKeys.list(missionId!, includeArchived),
    queryFn: () =>
      api.get<{ schedules: MissionScheduleResponse[] }>(
        `/missions/${missionId}/schedules?include_archived=${includeArchived}`,
      ),
    select: (data) => data.schedules,
    enabled: !!missionId,
  })
}

/** One schedule with its next fire times from Temporal. */
export function useMissionSchedule(missionId: string | undefined, scheduleId: string | undefined) {
  return useQuery({
    queryKey: missionScheduleKeys.detail(missionId!, scheduleId!),
    queryFn: () =>
      api.get<MissionScheduleResponse>(`/missions/${missionId}/schedules/${scheduleId}`),
    enabled: !!missionId && !!scheduleId,
  })
}

function useScheduleMutation<TVars>(
  missionId: string,
  mutationFn: (vars: TVars) => Promise<MissionScheduleResponse | void>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: missionScheduleKeys.all(missionId) })
    },
  })
}

export function useCreateMissionSchedule(missionId: string) {
  return useScheduleMutation(missionId, (data: MissionScheduleCreate) =>
    api.post<MissionScheduleResponse>(`/missions/${missionId}/schedules`, data),
  )
}

export function useUpdateMissionSchedule(missionId: string) {
  return useScheduleMutation(
    missionId,
    ({ scheduleId, data }: { scheduleId: string; data: MissionScheduleUpdate }) =>
      api.patch<MissionScheduleResponse>(`/missions/${missionId}/schedules/${scheduleId}`, data),
  )
}

export function usePauseMissionSchedule(missionId: string) {
  return useScheduleMutation(missionId, (scheduleId: string) =>
    api.post<MissionScheduleResponse>(`/missions/${missionId}/schedules/${scheduleId}/pause`),
  )
}

export function useResumeMissionSchedule(missionId: string) {
  return useScheduleMutation(missionId, (scheduleId: string) =>
    api.post<MissionScheduleResponse>(`/missions/${missionId}/schedules/${scheduleId}/resume`),
  )
}

/** DELETE archives the schedule; the row stays, with status `archived`. */
export function useArchiveMissionSchedule(missionId: string) {
  return useScheduleMutation(missionId, (scheduleId: string) =>
    api.del(`/missions/${missionId}/schedules/${scheduleId}`),
  )
}
