import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { ATTENTION_POLL_MS } from '@/lib/constants'
import type { AttentionResponse } from '@/types'

export const attentionKeys = {
  all: ['attention'] as const,
}

/**
 * What needs a person across the caller's missions: the dashboard list and, through
 * `pending_counts`, the sidebar badges.
 *
 * Inside a mission the mission stream invalidates this key when a plan, gate or
 * workflow-input event arrives. The dashboard has no such stream, so the query also
 * polls. Every caller shares one key, so the sidebar and the dashboard make one request.
 */
export function useAttention() {
  return useQuery({
    queryKey: attentionKeys.all,
    queryFn: () => api.get<AttentionResponse>('/attention'),
    refetchInterval: ATTENTION_POLL_MS,
  })
}
