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
