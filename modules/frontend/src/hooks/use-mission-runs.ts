/**
 * Mission run hooks (Plan 88). The api client unwraps the ApiResponse
 * envelope; every mutation invalidates ['mission-runs', missionId].
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  MissionRunCreate,
  MissionRunDetailResponse,
  MissionRunListResponse,
  MissionRunResponse,
  MissionRunStatus,
} from '@/types'

/** Statuses of a run that has not ended; lists poll while any row has one. */
export const ACTIVE_RUN_STATUSES: ReadonlySet<MissionRunStatus> = new Set([
  'pending',
  'running',
  'awaiting_gate',
  'paused',
])

const POLL_MS = 5000

export const missionRunKeys = {
  all: (missionId: string) => ['mission-runs', missionId] as const,
  list: (missionId: string, filters: MissionRunFilters) =>
    ['mission-runs', missionId, 'list', filters] as const,
  detail: (missionId: string, runIdOrSeq: string) =>
    ['mission-runs', missionId, 'detail', runIdOrSeq] as const,
}

export interface MissionRunFilters {
  statuses?: MissionRunStatus[]
  limit?: number
  beforeSequence?: number
}

export function useMissionRuns(missionId: string | undefined, filters: MissionRunFilters) {
  return useQuery({
    queryKey: missionRunKeys.list(missionId!, filters),
    queryFn: () => {
      const params = new URLSearchParams()
      for (const s of filters.statuses ?? []) params.append('status', s)
      if (filters.limit !== undefined) params.set('limit', String(filters.limit))
      if (filters.beforeSequence !== undefined)
        params.set('before_sequence', String(filters.beforeSequence))
      const qs = params.toString()
      return api.get<MissionRunListResponse>(`/missions/${missionId}/runs${qs ? `?${qs}` : ''}`)
    },
    enabled: !!missionId,
    refetchInterval: (query) =>
      query.state.data?.runs.some((r) => ACTIVE_RUN_STATUSES.has(r.status)) ? POLL_MS : false,
  })
}

/** One run by id or sequence, with its execution record id, tasks and digest. */
export function useMissionRun(missionId: string | undefined, runIdOrSeq: string | undefined) {
  return useQuery({
    queryKey: missionRunKeys.detail(missionId!, runIdOrSeq!),
    queryFn: () =>
      api.get<MissionRunDetailResponse>(`/missions/${missionId}/runs/${runIdOrSeq}`),
    enabled: !!missionId && !!runIdOrSeq,
    refetchInterval: (query) =>
      query.state.data && ACTIVE_RUN_STATUSES.has(query.state.data.run.status) ? POLL_MS : false,
  })
}

export function useStartMissionRun(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MissionRunCreate) =>
      api.post<MissionRunResponse>(`/missions/${missionId}/runs`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: missionRunKeys.all(missionId) })
    },
  })
}

export function useCancelMissionRun(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) =>
      api.post<MissionRunResponse>(`/missions/${missionId}/runs/${runId}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: missionRunKeys.all(missionId) })
    },
  })
}
