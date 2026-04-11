/**
 * useMissionArtifacts — durable mission artifacts (Plan 43).
 *
 * Replaces the old ephemeral Zustand `workspaceStore.artifacts` slice
 * with a react-query hook backed by
 * `GET /api/v1/missions/:id/artifacts`. Artifacts now survive page
 * refresh, session end, and backend restart — they're persisted by
 * `persist_mission_results` after each run.
 *
 * Live-preview path is unchanged: the `streamingArtifact` slice in
 * `stores/workspace.ts` still consumes `agent.response.chunk` events
 * for in-flight agent output, and the `mission.artifact.found` SSE
 * event is routed in `layout.tsx` as an invalidation trigger for this
 * query so newly-persisted artifacts appear without a page refresh.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

// ── Types ────────────────────────────────────────────────────────────────

export type ArtifactType = 'report' | 'finding' | 'code' | 'data' | 'file'

export type ArtifactContentType = 'text' | 'markdown' | 'json' | 'code'

/** One artifact row as returned by the API. Mirrors the backend
 *  MissionArtifactResponse schema one-to-one.
 */
export interface MissionArtifact {
  id: string
  mission_id: string
  execution_record_id: string | null
  task_execution_id: string | null

  agent_id: string
  artifact_type: ArtifactType | string
  title: string
  content_type: ArtifactContentType | string
  language: string | null

  content_text: string | null
  storage_url: string | null

  created_at: string
  updated_at: string
}

interface MissionArtifactsResponse {
  mission_id: string
  artifacts: MissionArtifact[]
  count: number
}

// ── Query keys ───────────────────────────────────────────────────────────

export const artifactKeys = {
  list: (missionId: string) => ['missions', missionId, 'artifacts'] as const,
}

// ── Queries ──────────────────────────────────────────────────────────────

/**
 * Fetch the persisted artifacts for a mission, newest first.
 *
 * The backend caps at 500; we default the client request to 50 (the
 * old ephemeral store's cap) because the ArtifactsPanel only shows a
 * vertical list and the UX wasn't designed for hundreds of rows.
 *
 * Cache refresh strategy:
 *   - `staleTime` is 30 seconds — the query is fresh between clicks
 *     within a session.
 *   - `layout.tsx` invalidates this query on every incoming
 *     `mission.artifact.found` SSE event, so newly-persisted rows
 *     appear immediately without a user refresh.
 */
export function useMissionArtifacts(
  missionId: string | undefined,
  options: { limit?: number; artifactType?: ArtifactType } = {},
) {
  const { limit = 50, artifactType } = options
  const query = new URLSearchParams()
  query.set('limit', String(limit))
  if (artifactType) query.set('artifact_type', artifactType)

  return useQuery({
    queryKey: artifactKeys.list(missionId!),
    queryFn: async () => {
      const resp = await api.get<MissionArtifactsResponse>(
        `/missions/${missionId}/artifacts?${query.toString()}`,
      )
      return resp.artifacts
    },
    enabled: !!missionId,
    staleTime: 30_000,
  })
}
