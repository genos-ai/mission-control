/**
 * NodePalette — command-palette-style search for adding workflow nodes.
 * Opens with Space key on the canvas, filters by typing, inserts on Enter/click.
 */

import { useEffect, useRef, useState } from 'react'
import { Bot, GitBranch, Bell, UserRound, Wrench, Sparkles, Split, Merge, Layers } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface NodePaletteEntry {
  type: string
  label: string
  description: string
  icon: LucideIcon
  color: string
}

const ENTRIES: NodePaletteEntry[] = [
  { type: 'agent_step', label: 'Agent Step', description: 'Invoke a registered agent', icon: Bot, color: 'text-blue-400' },
  { type: 'condition', label: 'Condition', description: 'If/else branch on expression', icon: GitBranch, color: 'text-cyan-500' },
  { type: 'notification', label: 'Notification', description: 'Send a message (Telegram, SSE)', icon: Bell, color: 'text-teal-500' },
  { type: 'human_input', label: 'Human Input', description: 'Pause and wait for response', icon: UserRound, color: 'text-orange-500' },
  { type: 'tool_call', label: 'Tool Call', description: 'Call a tool directly', icon: Wrench, color: 'text-slate-400' },
  { type: 'llm_call', label: 'LLM Call', description: 'Raw LLM prompt, no agent', icon: Sparkles, color: 'text-amber-400' },
  { type: 'branch', label: 'Fork', description: 'Split into parallel paths', icon: Split, color: 'text-zinc-400' },
  { type: 'merge', label: 'Join', description: 'Sync barrier for parallel paths', icon: Merge, color: 'text-zinc-400' },
  { type: 'sub_workflow', label: 'Sub-Workflow', description: 'Invoke another saved workflow', icon: Layers, color: 'text-indigo-400' },
]

interface NodePaletteProps {
  onSelect: (nodeType: string) => void
  onClose: () => void
}

export function NodePalette({ onSelect, onClose }: NodePaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const filtered = query
    ? ENTRIES.filter(
        (e) =>
          e.label.toLowerCase().includes(query.toLowerCase()) ||
          e.type.includes(query.toLowerCase()) ||
          e.description.toLowerCase().includes(query.toLowerCase()),
      )
    : ENTRIES

  // Focus on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Reset selection when filter changes
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.min(prev + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[selectedIndex]) {
        onSelect(filtered[selectedIndex].type)
      }
    }
  }

  return (
    <div className="absolute left-1/2 top-24 z-50 -translate-x-1/2 w-[320px] rounded-lg border bg-card shadow-xl">
      <input
        ref={inputRef}
        type="text"
        className="w-full rounded-t-lg border-b bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground/50"
        placeholder="Add node… (type to filter)"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Delay to allow click on list items
          setTimeout(onClose, 150)
        }}
      />
      <div className="max-h-[280px] overflow-y-auto py-1">
        {filtered.length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">No matching node types</p>
        )}
        {filtered.map((entry, i) => {
          const Icon = entry.icon
          return (
            <button
              key={entry.type}
              className={[
                'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm transition-colors',
                i === selectedIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/50',
              ].join(' ')}
              onMouseEnter={() => setSelectedIndex(i)}
              onMouseDown={(e) => {
                e.preventDefault() // prevent blur
                onSelect(entry.type)
              }}
            >
              <Icon className={`h-4 w-4 shrink-0 ${entry.color}`} />
              <div className="min-w-0">
                <span className="font-medium">{entry.label}</span>
                <span className="ml-1.5 text-[11px] text-muted-foreground">{entry.description}</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
