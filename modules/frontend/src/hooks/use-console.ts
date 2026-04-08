import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { ConsoleEvent } from '@/stores/console'

export function useConsoleHistory(missionId: string | undefined) {
  return useQuery({
    queryKey: ['missions', missionId, 'console', 'history'],
    queryFn: () =>
      api.get<{ events: ConsoleEvent[] }>(
        `/missions/${missionId}/console/history`,
      ),
    select: (data) => data.events,
    enabled: !!missionId,
    staleTime: 30_000, // refetch after 30s to pick up completed runs
  })
}
