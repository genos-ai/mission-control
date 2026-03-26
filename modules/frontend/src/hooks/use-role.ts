export type MissionRole = 'owner' | 'maintainer' | 'viewer'

/**
 * Get the current user's role within a specific mission.
 *
 * Phase F1: stub — returns null (unknown).
 * Phase F2+: backed by React Query cache of mission members.
 */
export function useRole(_missionId: string | undefined): {
  role: MissionRole | null
  isOwner: boolean
  isMaintainer: boolean
  isViewer: boolean
  canEdit: boolean
  canOperate: boolean
} {
  // TODO: Phase F2 — query GET /missions/:id/members and find current user
  const role: MissionRole | null = null

  return {
    role,
    isOwner: role === 'owner',
    isMaintainer: role === 'maintainer',
    isViewer: role === 'viewer',
    canEdit: role === 'owner',
    canOperate: role === 'owner' || role === 'maintainer',
  }
}
