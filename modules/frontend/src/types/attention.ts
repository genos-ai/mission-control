/**
 * Attention types: what needs a person across the missions they can see.
 */

export type AttentionKind = 'task_approval' | 'gate' | 'human_input' | 'retry'

/**
 * One thing that needs attention. The backend writes the title, detail and link.
 * A gate or human-input request is an item each; proposed and failed tasks are one item
 * per mission, and `count` says how many tasks.
 */
export interface AttentionItem {
  mission_id: string
  mission_name: string
  kind: AttentionKind
  title: string
  detail: string
  count: number
  created_at: string
  href: string
}

export interface AttentionResponse {
  /** Most urgent first. */
  items: AttentionItem[]
  /** Number of items per mission id, for the sidebar badge. */
  pending_counts: Record<string, number>
}
