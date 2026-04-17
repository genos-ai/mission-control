import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface KnowledgeEntry {
  id: string
  kind: string
  source_table: string
  title: string
  body: string
  domain_tags: string[]
  mission_id: string | null
  confidence: number | null
  distance: number | null
  created_at: string | null
}

export const knowledgeKeys = {
  search: (params: Record<string, unknown>) => ['knowledge', 'search', params] as const,
  missionKnowledge: (missionId: string) => ['missions', missionId, 'knowledge'] as const,
}

export function useKnowledgeSearch(opts: {
  q: string
  tags?: string
  kinds?: string
  mode?: 'structured' | 'hybrid' | 'semantic'
  platform_only?: boolean
  mission_id?: string
  enabled?: boolean
}) {
  const params = new URLSearchParams()
  if (opts.q) params.set('q', opts.q)
  if (opts.tags) params.set('tags', opts.tags)
  if (opts.kinds) params.set('kinds', opts.kinds)
  if (opts.mode) params.set('mode', opts.mode)
  if (opts.platform_only) params.set('platform_only', 'true')
  if (opts.mission_id) params.set('mission_id', opts.mission_id)

  return useQuery({
    queryKey: knowledgeKeys.search(opts),
    queryFn: () =>
      api.get<KnowledgeEntry[]>(`/knowledge/search?${params.toString()}`),
    enabled: opts.enabled !== false && opts.q.length > 0,
  })
}

export function useMissionKnowledge(missionId: string | undefined) {
  return useQuery({
    queryKey: knowledgeKeys.missionKnowledge(missionId!),
    queryFn: () =>
      api.get<Record<string, unknown>>(`/missions/${missionId}/knowledge`),
    enabled: !!missionId,
  })
}
