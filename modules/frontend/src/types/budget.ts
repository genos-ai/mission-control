/**
 * Mission budget types (Plan 88 step 88.4.1, contracts 3.5.3).
 *
 * Mirrors backend/schemas/budget.py. `breach` carries the lowercase
 * MissionPauseReason value the API returns, or null.
 */

export type BudgetBreach = 'budget_run_cap' | 'budget_monthly_cap' | 'budget_lifetime_cap'

export interface BudgetStatusResponse {
  per_run_usd: number
  per_month_usd: number
  lifetime_usd: number | null
  month_spent_usd: number
  lifetime_spent_usd: number
  active_run_spent_usd: number
  breach: BudgetBreach | null
}

export interface BudgetCapsUpdate {
  per_run_usd: number
  per_month_usd: number
  /** null removes the lifetime cap. */
  lifetime_usd: number | null
}
