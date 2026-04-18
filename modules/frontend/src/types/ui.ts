/**
 * UI-related types — drawer content, notifications, etc.
 */

// Drawer types
export type DrawerContentType =
  | 'run-events'
  | 'agent-events'
  | 'prompt-history'
  | 'architect-chat'
  | 'event-log'
  | 'output-preview'
  | 'cost-breakdown'
  | 'agent-detail'

// Notification types
export interface Notification {
  id: string
  type: 'gate_approval' | 'run_failed' | 'run_completed' | 'budget_warning'
  title: string
  body: string
  mission_id: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string
}
