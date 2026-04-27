/**
 * VariableAutocomplete — textarea with @node.* / @context.* dropdown suggestions.
 *
 * When the user types `@` (or `{{@` in template mode), a dropdown appears
 * with available upstream node IDs and context keys. Selecting an item
 * inserts the full reference at the cursor position.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Textarea } from '@/components/ui/textarea'

interface VariableAutocompleteProps {
  value: string
  onChange: (value: string) => void
  /** IDs of upstream nodes (from depends_on / edges). */
  upstreamNodeIds: string[]
  /** Whether to use {{@...}} template syntax (true) or bare @... expression syntax (false). */
  templateMode?: boolean
  className?: string
  placeholder?: string
  rows?: number
}

interface Suggestion {
  label: string
  insert: string
  detail?: string
}

function buildSuggestions(
  upstreamNodeIds: string[],
  templateMode: boolean,
): Suggestion[] {
  const wrap = (ref: string) => (templateMode ? `{{${ref}}}` : ref)
  const suggestions: Suggestion[] = []

  for (const nodeId of upstreamNodeIds) {
    suggestions.push({
      label: `@node.${nodeId}`,
      insert: wrap(`@node.${nodeId}.output`),
      detail: 'Full output',
    })
    suggestions.push({
      label: `@node.${nodeId}.result`,
      insert: wrap(`@node.${nodeId}.result`),
      detail: 'Result field',
    })
    suggestions.push({
      label: `@node.${nodeId}.summary`,
      insert: wrap(`@node.${nodeId}.summary`),
      detail: 'Summary field',
    })
  }

  suggestions.push({
    label: '@context.query',
    insert: wrap('@context.query'),
    detail: 'Workflow context',
  })
  suggestions.push({
    label: '@context.mission_id',
    insert: wrap('@context.mission_id'),
    detail: 'Mission ID',
  })

  return suggestions
}

export function VariableAutocomplete({
  value,
  onChange,
  upstreamNodeIds,
  templateMode = true,
  className = '',
  placeholder,
  rows,
}: VariableAutocompleteProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [showMenu, setShowMenu] = useState(false)
  const [filter, setFilter] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [insertPos, setInsertPos] = useState<{ start: number; end: number } | null>(null)

  const allSuggestions = buildSuggestions(upstreamNodeIds, templateMode)
  const filtered = filter
    ? allSuggestions.filter((s) => s.label.toLowerCase().includes(filter.toLowerCase()))
    : allSuggestions

  // Detect @ trigger
  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value
      onChange(newValue)

      const cursor = e.target.selectionStart ?? 0
      const textBefore = newValue.slice(0, cursor)

      // Find the @ trigger: either bare `@` (expression mode) or `{{@` (template mode)
      const atIndex = templateMode
        ? (() => {
            const tplIdx = textBefore.lastIndexOf('{{@')
            return tplIdx >= 0 ? tplIdx + 2 : -1 // point to the @
          })()
        : textBefore.lastIndexOf('@')

      if (atIndex >= 0 && cursor - atIndex <= 40) {
        const typed = textBefore.slice(atIndex + 1) // text after @
        // Only show if no closing }} between @ and cursor (in template mode)
        if (templateMode && typed.includes('}}')) {
          setShowMenu(false)
          return
        }
        // Only show if no space after @ (bare mode)
        if (!templateMode && typed.includes(' ')) {
          setShowMenu(false)
          return
        }
        setFilter(typed ? `@${typed}` : '')
        setInsertPos({ start: atIndex, end: cursor })
        setShowMenu(true)
        setSelectedIndex(0)
      } else {
        setShowMenu(false)
      }
    },
    [onChange, templateMode],
  )

  // Insert selected suggestion
  const insertSuggestion = useCallback(
    (suggestion: Suggestion) => {
      if (!insertPos) return
      const textarea = textareaRef.current
      if (!textarea) return

      // In template mode, also consume the leading {{ if present
      let start = insertPos.start
      if (templateMode && value.slice(start - 2, start) === '{{') {
        start -= 2
      }

      const before = value.slice(0, start)
      const after = value.slice(insertPos.end)
      const newValue = before + suggestion.insert + after
      onChange(newValue)
      setShowMenu(false)

      // Restore cursor position after the inserted text
      const newCursor = before.length + suggestion.insert.length
      requestAnimationFrame(() => {
        textarea.selectionStart = newCursor
        textarea.selectionEnd = newCursor
        textarea.focus()
      })
    },
    [insertPos, value, onChange, templateMode],
  )

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!showMenu || filtered.length === 0) return

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex((prev) => Math.min(prev + 1, filtered.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex((prev) => Math.max(prev - 1, 0))
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (showMenu && filtered[selectedIndex]) {
          e.preventDefault()
          insertSuggestion(filtered[selectedIndex])
        }
      } else if (e.key === 'Escape') {
        setShowMenu(false)
      }
    },
    [showMenu, filtered, selectedIndex, insertSuggestion],
  )

  // Close menu on blur (delayed to allow click)
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        textareaRef.current &&
        !textareaRef.current.contains(e.target as Node)
      ) {
        setShowMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="relative">
      <Textarea
        ref={textareaRef}
        className={`${className}`}
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={rows}
      />
      {showMenu && filtered.length > 0 && (
        <div
          ref={menuRef}
          className="absolute left-0 top-full z-50 mt-1 max-h-[180px] w-full overflow-y-auto rounded-md border bg-popover shadow-md"
        >
          {filtered.map((s, i) => (
            <button
              key={s.insert}
              className={[
                'flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-xs',
                i === selectedIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/50',
              ].join(' ')}
              onMouseEnter={() => setSelectedIndex(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                insertSuggestion(s)
              }}
            >
              <span className="font-mono">{s.label}</span>
              {s.detail && (
                <span className="text-[10px] text-muted-foreground">{s.detail}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
