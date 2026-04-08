export const ROUTES = {
  LOGIN: '/login',
  DASHBOARD: '/',
  PROFILE: '/profile',
  CATALOG: '/catalog',

  // Mission workspace
  MISSION: (id: string) => `/missions/${id}`,
  MISSION_OVERVIEW: (id: string) => `/missions/${id}/overview`,
  MISSION_TEAM: (id: string) => `/missions/${id}/team`,
  MISSION_CHAT: (id: string) => `/missions/${id}/chat`,
  MISSION_WORKFLOWS: (id: string) => `/missions/${id}/workflows`,
  MISSION_RUNS: (id: string) => `/missions/${id}/runs`,
  MISSION_CONSOLE: (id: string) => `/missions/${id}/console`,
  MISSION_RUN_LIVE: (missionId: string, runId: string) =>
    `/missions/${missionId}/runs/${runId}`,
  MISSION_WORKSHOP: (id: string) => `/missions/${id}/workshop`,
  MISSION_CONTEXT: (id: string) => `/missions/${id}/context`,

  // Admin
  ADMIN: '/admin',
  ADMIN_CATALOG: '/admin/catalog',
  ADMIN_METRICS: '/admin/metrics',
  ADMIN_CONFIG: '/admin/config',
  ADMIN_HEALTH: '/admin/health',
  ADMIN_USERS: '/admin/users',
} as const

export const API_BASE = '/api/v1'
