import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** One manual gate request, as GET /missions/{id}/gates/{rid} returns it. */
export interface GateRequestDetail {
  id: string
  mission_id: string
  plan_id: string | null
  gate_type: string
  status: string
  created_at: string
  decided_at: string | null
  timed_out_at: string | null
  context_json: Record<string, unknown>
  decision_json: Record<string, unknown> | null
  /** The decision actions the backend accepts for this gate's type. */
  allowed_actions: string[]
}

export const gateKeys = {
  detail: (missionId: string, requestId: string) =>
    ['missions', missionId, 'gates', requestId] as const,
}

export function useGateRequest(missionId: string, requestId: string) {
  return useQuery({
    queryKey: gateKeys.detail(missionId, requestId),
    queryFn: () =>
      api.get<GateRequestDetail>(`/missions/${missionId}/gates/${requestId}`),
    enabled: !!missionId && !!requestId,
  })
}

export function useDecideGate(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: { requestId: string; action: string; reason?: string }) =>
      api.post(`/missions/${missionId}/gates/${params.requestId}/decide`, {
        action: params.action,
        reason: params.reason ?? null,
      }),
    onSuccess: (_data, params) => {
      qc.invalidateQueries({ queryKey: gateKeys.detail(missionId, params.requestId) })
      qc.invalidateQueries({ queryKey: ['attention'] })
    },
  })
}
