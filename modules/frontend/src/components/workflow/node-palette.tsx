/**
 * NodePalette — command-palette-style search for adding workflow nodes.
 * Opens with Space key on the canvas, filters by typing, inserts on Enter/click.
 */

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { TONE_TEXT } from '@/lib/tone-class'
import { STEP_TYPES, STEP_TYPE_ORDER } from './workflow-editor-types'

interface NodePaletteProps {
  onSelect: (nodeType: string) => void
  onClose: () => void
}

export function NodePalette({ onSelect, onClose }: NodePaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const needle = query.toLowerCase()
  const filtered = needle
    ? STEP_TYPE_ORDER.filter((type) => {
        const { label, description } = STEP_TYPES[type]
        return (
          label.toLowerCase().includes(needle) ||
          type.includes(needle) ||
          description.toLowerCase().includes(needle)
        )
      })
    : STEP_TYPE_ORDER

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
        onSelect(filtered[selectedIndex])
      }
    }
  }

  return (
    <div className="absolute left-1/2 top-24 z-50 w-[320px] -translate-x-1/2 rounded-card border border-panel-border bg-popover shadow-lg">
      <input
        ref={inputRef}
        type="text"
        className="w-full rounded-t-card bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-subtle"
        placeholder="Add node… (type to filter)"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Delay to allow click on list items
          setTimeout(onClose, 150)
        }}
      />
      <div className="max-h-[280px] overflow-y-auto border-t border-line py-1">
        {filtered.length === 0 && <p className="px-3 py-2 text-xs text-subtle">No matching node types</p>}
        {filtered.map((type, i) => {
          const { label, description, icon: Icon, tone } = STEP_TYPES[type]
          return (
            <button
              key={type}
              className={cn(
                'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm transition-colors duration-150',
                i === selectedIndex ? 'bg-raised text-foreground' : 'hover:bg-hover',
              )}
              onMouseEnter={() => setSelectedIndex(i)}
              onMouseDown={(e) => {
                e.preventDefault() // prevent blur
                onSelect(type)
              }}
            >
              <Icon className={cn('h-4 w-4 shrink-0', TONE_TEXT[tone])} />
              <div className="min-w-0">
                <span className="font-medium">{label}</span>
                <span className="ml-1.5 text-2xs text-subtle">{description}</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
