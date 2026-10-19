import type { ReactNode } from 'react'
import { AlertTriangle, Bot, Brain, Loader2 } from 'lucide-react'

import { IconTile } from '@/components/ui/icon-tile'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import { fmtCost } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import type { SessionMessage } from '@/types'
import { agentLabel } from './chat-constants'

export interface AgentMessageProps {
  /** Full agent name, e.g. mission.director.agent; empty when unknown. */
  agentId: string
  meta?: string
  failed?: boolean
  children: ReactNode
}

/** An agent's turn: avatar, name and meta line, then the body. */
export function AgentMessage({ agentId, meta, failed = false, children }: AgentMessageProps) {
  const style = agentStyle(agentId)
  return (
    <div className="flex gap-2.5">
      <IconTile icon={failed ? AlertTriangle : agentId ? style.icon : Bot} tone={failed ? 'danger' : style.tone} size="sm" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="text-xs font-medium">{agentId ? agentLabel(agentId) : 'Assistant'}</span>
          {meta && <span className="font-mono text-2xs text-subtle">{meta}</span>}
        </div>
        {children}
      </div>
    </div>
  )
}

/** The agent's reasoning, shown in a faint violet box. */
export function ThinkingBlock({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <details open className="mb-3 rounded-card border border-violet/20 bg-violet/5 px-3 py-2">
      <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-violet">
        <Brain className="h-3 w-3" />
        Thinking
        {live && <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />}
      </summary>
      <p className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {text}
      </p>
    </details>
  )
}

export function MessageBubble({ message }: { message: SessionMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[82%] rounded-[14px_14px_4px_14px] border border-line bg-sidebar-active px-3.5 py-2.5 text-md [overflow-wrap:anywhere]">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    )
  }

  const failed = message.role === 'error' || message.status === 'failed'
  const meta = [
    formatUtc(message.created_at),
    message.cost_usd != null ? fmtCost(message.cost_usd) : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <AgentMessage agentId={message.sender_id ?? ''} meta={meta} failed={failed}>
      {message.thinking && <ThinkingBlock text={message.thinking} />}
      <div className={cn(failed && 'rounded-card border border-danger/20 bg-danger/10 p-3')}>
        <MarkdownRenderer content={message.content} className="text-md text-text-2 [overflow-wrap:anywhere]" />
      </div>
      {message.status === 'streaming' && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-subtle">
          <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
          Still generating…
        </div>
      )}
    </AgentMessage>
  )
}
