import {
  Activity,
  DollarSign,
  FileText,
  GitBranch,
  Kanban,
  Lightbulb,
  ListChecks,
  MessageSquare,
  Package,
  Radio,
  Terminal,
  Users,
  type LucideIcon,
} from 'lucide-react'

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
  MISSION_ARTIFACTS: (id: string) => `/missions/${id}/artifacts`,
  MISSION_KNOWLEDGE: (id: string) => `/missions/${id}/knowledge`,
  MISSION_COSTS: (id: string) => `/missions/${id}/costs`,
  MISSION_WORKFLOWS: (id: string) => `/missions/${id}/workflows`,
  MISSION_WORKFLOW_EDIT: (id: string, workflowId: string) =>
    `/missions/${id}/workflows/${workflowId}/edit`,
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

export interface MissionNavItem {
  label: string
  icon: LucideIcon
  to: (missionId: string) => string
}

/** The mission's sections, in the three groups the sidebar shows: Work, Setup, Observe. */
export const MISSION_NAV_GROUPS: readonly (readonly MissionNavItem[])[] = [
  [
    { label: 'Overview', icon: Activity, to: ROUTES.MISSION_OVERVIEW },
    { label: 'Chat', icon: MessageSquare, to: ROUTES.MISSION_CHAT },
    { label: 'Plan', icon: Kanban, to: ROUTES.MISSION_PLAN },
    { label: 'Runs', icon: ListChecks, to: ROUTES.MISSION_RUNS },
    { label: 'Artifacts', icon: Package, to: ROUTES.MISSION_ARTIFACTS },
  ],
  [
    { label: 'Team', icon: Users, to: ROUTES.MISSION_TEAM },
    { label: 'Workflows', icon: GitBranch, to: ROUTES.MISSION_WORKFLOWS },
    { label: 'Context', icon: FileText, to: ROUTES.MISSION_CONTEXT },
    { label: 'Knowledge', icon: Lightbulb, to: ROUTES.MISSION_KNOWLEDGE },
  ],
  [
    { label: 'Narrative', icon: Radio, to: ROUTES.MISSION_NARRATIVE },
    { label: 'Costs', icon: DollarSign, to: ROUTES.MISSION_COSTS },
    { label: 'Console', icon: Terminal, to: ROUTES.MISSION_CONSOLE },
  ],
]

/** How often the attention list is re-read where no live stream tells us it changed (the dashboard). */
export const ATTENTION_POLL_MS = 30_000

/** How long Log out waits for the server to end the session before signing out locally regardless. */
export const LOGOUT_TIMEOUT_MS = 5_000

/** The shortest password the API accepts (`min_length` of the password fields in schemas/auth.py). */
export const PASSWORD_MIN_LENGTH = 12
