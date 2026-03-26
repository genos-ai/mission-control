import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AgentCatalogItem, AgentCatalogDetail } from '@/types'

export const catalogKeys = {
  all: ['catalog'] as const,
  detail: (name: string) => ['catalog', name] as const,
}

export function useCatalog() {
  return useQuery({
    queryKey: catalogKeys.all,
    queryFn: () =>
      api.get<{ agents: AgentCatalogItem[]; total: number }>('/catalog/agents'),
    select: (data) => data.agents,
  })
}

export function useCatalogAgent(name: string | undefined) {
  return useQuery({
    queryKey: catalogKeys.detail(name!),
    queryFn: () => api.get<AgentCatalogDetail>(`/catalog/agents/${name}`),
    enabled: !!name,
  })
}
