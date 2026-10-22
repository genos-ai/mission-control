/** How an intent's `source` reads to a person. Unknown sources show as the raw value. */
export const INTENT_SOURCE_LABELS: Record<string, string> = {
  user_chat: 'User',
  user_cli: 'CLI',
  director_inferred: 'Director',
  system: 'System',
}

export function intentSourceLabel(source: string): string {
  return INTENT_SOURCE_LABELS[source] ?? source
}
