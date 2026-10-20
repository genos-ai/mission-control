/**
 * UI-related types — drawer content, notifications, etc.
 */

// Drawer types
export type DrawerContentType = 'run-events' | 'prompt-history' | 'agent-detail'

// Notification types
export interface Notification {
  id: string
  type: 'gate_approval' | 'run_failed' | 'run_completed' | 'budget_warning' | 'human_input_needed'
  title: string
  body: string
  mission_id: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string
}
