import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  MissionTeamMember,
  MissionTeamAddRequest,
  UserPromptUpdateRequest,
  PromptHistoryResponse,
} from '@/types'

export const teamKeys = {
  all: (missionId: string) => ['missions', missionId, 'team'] as const,
  // The enabled-only list keeps the original key, so callers that never pass the flag
  // (chat roster, overview, console) share one cache entry as before.
  list: (missionId: string, enabledOnly: boolean) =>
    enabledOnly
      ? teamKeys.all(missionId)
      : ([...teamKeys.all(missionId), 'including-disabled'] as const),
  promptHistory: (missionId: string, memberId: string) =>
    ['missions', missionId, 'team', memberId, 'prompt-history'] as const,
}

/** The mission's team. Pass `enabledOnly = false` to include members switched off. */
export function useTeam(missionId: string | undefined, enabledOnly = true) {
  return useQuery({
    queryKey: teamKeys.list(missionId!, enabledOnly),
    queryFn: () =>
      api.get<{ team_members: MissionTeamMember[]; total: number }>(
        `/missions/${missionId}/team?enabled_only=${enabledOnly}`,
      ),
    select: (data) => data.team_members,
    enabled: !!missionId,
  })
}

export function useSeedTeam(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.post<{ added_count: number }>(
        `/missions/${missionId}/team/seed`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
    },
  })
}

export function useAddToTeam(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: MissionTeamAddRequest) =>
      api.post<MissionTeamMember>(`/missions/${missionId}/team`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
    },
  })
}

export function useRemoveFromTeam(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (memberId: string) =>
      api.del(`/missions/${missionId}/team/${memberId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
    },
  })
}

export function useUpdatePrompt(missionId: string, memberId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: UserPromptUpdateRequest) =>
      api.put<MissionTeamMember>(
        `/missions/${missionId}/team/${memberId}/prompt`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
      qc.invalidateQueries({
        queryKey: teamKeys.promptHistory(missionId, memberId),
      })
    },
  })
}

export function useUpdateConstraints(missionId: string, memberId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.patch<MissionTeamMember>(
        `/missions/${missionId}/team/${memberId}/constraints`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
    },
  })
}

export function useToggleTeamMember(missionId: string, memberId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.patch<MissionTeamMember>(
        `/missions/${missionId}/team/${memberId}/enabled`,
        { enabled },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all(missionId) })
    },
  })
}

export function usePromptHistory(
  missionId: string | undefined,
  memberId: string | undefined,
) {
  return useQuery({
    queryKey: teamKeys.promptHistory(missionId!, memberId!),
    queryFn: () =>
      api.get<PromptHistoryResponse>(
        `/missions/${missionId}/team/${memberId}/prompt-history`,
      ),
    enabled: !!missionId && !!memberId,
  })
}
