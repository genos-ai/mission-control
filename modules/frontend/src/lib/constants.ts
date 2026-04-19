export const ROUTES = {
  LOGIN: '/login',
  DASHBOARD: '/',
  PROFILE: '/profile',
  CATALOG: '/catalog',

  // Mission tabs
  MISSION: (id: string) => `/missions/${id}`,
  MISSION_OVERVIEW: (id: string) => `/missions/${id}/overview`,
  MISSION_TEAM: (id: string) => `/missions/${id}/team`,
  MISSION_CHAT: (id: string) => `/missions/${id}/chat`,
  MISSION_PLAN: (id: string) => `/missions/${id}/plan`,
  MISSION_NARRATIVE: (id: string) => `/missions/${id}/narrative`,
  MISSION_CONSOLE: (id: string) => `/missions/${id}/console`,
  MISSION_CONTEXT: (id: string) => `/missions/${id}/context`,
  MISSION_RUNS: (id: string) => `/missions/${id}/runs`,
  MISSION_WORKFLOWS: (id: string) => `/missions/${id}/workflows`,
  MISSION_RUN_LIVE: (missionId: string, runId: string) =>
    `/missions/${missionId}/runs/${runId}`,

  // Admin
  ADMIN: '/admin',
  ADMIN_CATALOG: '/admin/catalog',
  ADMIN_METRICS: '/admin/metrics',
  ADMIN_CONFIG: '/admin/config',
  ADMIN_HEALTH: '/admin/health',
  ADMIN_USERS: '/admin/users',
  ADMIN_TOKEN_ECONOMICS: '/admin/token-economics',
} as const

export const API_BASE = '/api/v1'
