/**
 * Shared formatting utilities.
 */

/** Strip the `.agent` suffix for display: "software.quality.agent" → "software.quality". */
export function agentShortName(agentId: string): string {
  if (!agentId) return ''
  return agentId.endsWith('.agent') ? agentId.slice(0, -6) : agentId
}

/** Format a token count as a compact string (e.g. 1.5K, 2.3M). */
export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

/** Per-call and per-task cost, to the hundredth of a cent: "$0.0412". */
export function fmtCost(usd: number): string {
  return `$${usd.toFixed(4)}`
}

/** Totals and budgets, to the cent: "$212.40". */
export function fmtUsd(usd: number): string {
  return `$${usd.toFixed(2)}`
}

/** Display text for a status: "completed" -> "Completed", "timed_out" -> "Timed out". */
export function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ')
}
