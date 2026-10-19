import type { MissionPlan } from '@/hooks/use-mission-plan'

/** Tasks finished out of tasks that count: cancelled tasks are not part of the plan any more. */
export function planProgress(plan: MissionPlan): { done: number; total: number } {
  const counted = plan.tasks.filter((t) => t.status !== 'cancelled')
  return { done: counted.filter((t) => t.status === 'completed').length, total: counted.length }
}
