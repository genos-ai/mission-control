/** The model name without its provider prefix, e.g. "anthropic:claude-opus-4-20250514" → "claude-opus-4-20250514". The API's own name is shown as-is, so the label never misstates the version. */
export function modelLabel(name: string | undefined): string {
  if (!name) return 'Unknown'
  return name.includes(':') ? name.split(':')[1] : name
}
