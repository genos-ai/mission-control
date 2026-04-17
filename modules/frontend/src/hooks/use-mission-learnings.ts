import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface MissionLearning {
  id: string
  mission_id: string
  kind: string
  title: string
  body: string
  recommendation: string
  evidence: Record<string, unknown>
  domain_tags: string[]
  agent_names: string[]
  confidence: number
  occurrence_count: number
  platform_promoted: boolean
  promoted_at: string | null
  promoted_by: string | null
  contradicts_id: string | null
  status: string
  created_at: string
  updated_at: string
}

export const learningKeys = {
  list: (missionId: string) => ['missions', missionId, 'learnings'] as const,
  detail: (missionId: string, id: string) =>
    ['missions', missionId, 'learnings', id] as const,
  similar: (missionId: string, id: string) =>
    ['missions', missionId, 'learnings', id, 'similar'] as const,
}

export function useMissionLearnings(
  missionId: string | undefined,
  opts?: { kind?: string; domain_tags?: string },
) {
  const params = new URLSearchParams()
  if (opts?.kind) params.set('kind', opts.kind)
  if (opts?.domain_tags) params.set('domain_tags', opts.domain_tags)
  const qs = params.toString() ? `?${params.toString()}` : ''

  return useQuery({
    queryKey: [...learningKeys.list(missionId!), opts?.kind, opts?.domain_tags],
    queryFn: () =>
      api.get<{ items: MissionLearning[]; total: number }>(
        `/missions/${missionId}/learnings${qs}`,
      ),
    enabled: !!missionId,
  })
}

export function useLearningDetail(missionId: string, learningId: string) {
  return useQuery({
    queryKey: learningKeys.detail(missionId, learningId),
    queryFn: () =>
      api.get<MissionLearning>(`/missions/${missionId}/learnings/${learningId}`),
    enabled: !!missionId && !!learningId,
  })
}

export function useSimilarLearnings(missionId: string, learningId: string) {
  return useQuery({
    queryKey: learningKeys.similar(missionId, learningId),
    queryFn: () =>
      api.get<unknown[]>(
        `/missions/${missionId}/learnings/${learningId}/similar?limit=5`,
      ),
    enabled: !!missionId && !!learningId,
  })
}
