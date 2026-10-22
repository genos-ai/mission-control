/**
 * Presentation helpers for console events: what kind of row an event is, the
 * four values its grid row shows, and the clock format. Nothing here changes
 * what the API sent; it only picks which of its fields to show where.
 */

import { eventDetail } from '@/lib/event-utils'
import type { ConsoleEvent } from '@/stores/console'

export type ConsoleRowKind = 'narrative' | 'artifact' | 'chat' | 'execution' | 'task' | 'log'

export interface ConsoleRowView {
  kind: ConsoleRowKind
  source: string
  message: string
  error: boolean
  warning: boolean
}

/** A failure the console should flag, whichever field the emitter used to say so. */
export function isErrorEvent(event: ConsoleEvent): boolean {
  const d = event.data
  return (
    d.error === true ||
    d.level === 'error' ||
    d.phase === 'error' ||
    d.step === 'error' ||
    d.status === 'failed' ||
    event.event_type.includes('failed') ||
    event.event_type.includes('error')
  )
}

export function consoleRowKind(event: ConsoleEvent): ConsoleRowKind {
  const type = event.event_type
  if (type === 'mission.narrative') return 'narrative'
  if (type === 'mission.artifact.found') return 'artifact'
  if (event.category === 'chat' || type.startsWith('user.message') || type.startsWith('assistant.message')) {
    return 'chat'
  }
  if (type === 'execution.record') return 'execution'
  if (type.startsWith('task.') && !type.includes('attempt')) return 'task'
  return 'log'
}

/** Whether a chat event came from the person rather than an agent. */
export function isUserMessage(event: ConsoleEvent): boolean {
  const role = String(event.data.role ?? (event.event_type === 'user.message.sent' ? 'user' : 'assistant'))
  return role === 'user' || event.event_type === 'user.message.sent'
}

/** Drops markdown punctuation so a rendered-markdown field reads as one plain line in the log. */
function plainText(text: string): string {
  return text.replace(/[*_`#>]/g, '')
}

export function chatContent(event: ConsoleEvent): string {
  return String(event.data.content ?? event.data.full_content ?? '')
}

function chatSource(event: ConsoleEvent): string {
  if (isUserMessage(event)) return 'Human'
  const d = event.data
  const name = String(d.agent_id ?? d.sender_id ?? event.source ?? 'assistant')
  return name.endsWith('.agent') ? name.slice(0, -6) : name
}

export function consoleRowView(event: ConsoleEvent): ConsoleRowView {
  const d = event.data
  const kind = consoleRowKind(event)
  const error = isErrorEvent(event)
  const warning = !error && (d.level === 'warning' || event.event_type.includes('warning'))

  if (kind === 'chat') {
    const preview = plainText(chatContent(event)).slice(0, 120).replace(/\n/g, ' ')
    return { kind, source: chatSource(event), message: preview || '(empty)', error, warning }
  }

  // The row is one line of plain text; the markdown renders in the opened detail.
  const detail =
    kind === 'narrative'
      ? plainText(String(d.narrative ?? ''))
      : eventDetail(event.event_type, d)
  const message = error ? String(d.message ?? d.error_detail ?? d.reason ?? detail) : detail
  return { kind, source: event.source || String(d.agent_name ?? ''), message, error, warning }
}

/** Format output_data into a readable summary. */
export function formatOutput(output: Record<string, unknown>): string | null {
  const keys = Object.keys(output).filter((k) => k !== '_meta')
  if (keys.length === 0) return null

  for (const field of ['result', 'summary']) {
    const value = output[field]
    if (typeof value === 'string') return value.length > 500 ? value.slice(0, 500) + '…' : value
  }

  // Otherwise a compact JSON preview of the first few keys.
  const preview: Record<string, unknown> = {}
  for (const k of keys.slice(0, 5)) {
    const v = output[k]
    preview[k] = typeof v === 'string' && v.length > 200 ? v.slice(0, 200) + '…' : v
  }
  try {
    return JSON.stringify(preview, null, 2)
  } catch {
    return null
  }
}

/** Category for an SSE event that arrives without one (the standalone page, outside the mission layout). */
export function categorize(eventType: string): ConsoleEvent['category'] {
  // Chat first: agent.* below would otherwise claim agent.response.complete.
  if (
    eventType.startsWith('user.message') ||
    eventType.startsWith('assistant.message') ||
    eventType === 'agent.response.complete'
  ) {
    return 'chat'
  }
  if (
    eventType.startsWith('plan.') ||
    eventType.startsWith('agent.') ||
    eventType.startsWith('task.') ||
    eventType.startsWith('execution.') ||
    eventType.startsWith('decision.') ||
    eventType.startsWith('session.cost') ||
    eventType.startsWith('mission.')
  ) {
    return 'execution'
  }
  return 'system'
}

export function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}
