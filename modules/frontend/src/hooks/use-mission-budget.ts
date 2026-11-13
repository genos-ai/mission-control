/**
 * Mission budget hook (Plan 88 step 88.4.1). The api client unwraps the
 * ApiResponse envelope. Editing the caps arrives in 88.4.10.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { BudgetStatusResponse } from '@/types'

export const missionBudgetKeys = {
  budget: (missionId: string) => ['missions', missionId, 'budget'] as const,
}

/** Caps, this month's and lifetime spend, and any breached cap. */
export function useMissionBudget(missionId: string | undefined) {
  return useQuery({
    queryKey: missionBudgetKeys.budget(missionId!),
    queryFn: () => api.get<BudgetStatusResponse>(`/missions/${missionId}/budget`),
    enabled: !!missionId,
  })
}
