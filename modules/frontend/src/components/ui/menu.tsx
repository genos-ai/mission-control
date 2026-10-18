import { useRef, useState, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

import { useClickOutside } from '@/hooks/use-click-outside'
import { cn } from '@/lib/cn'

export interface MenuItem {
  label: string
  icon?: LucideIcon
  onSelect: () => void
  disabled?: boolean
  destructive?: boolean
  /** Draw a divider above this item. */
  separatorBefore?: boolean
}

export interface MenuProps {
  /** Accessible name for the trigger button. */
  label: string
  trigger: ReactNode
  items: MenuItem[]
  className?: string
  triggerClassName?: string
}

/** A button that opens a small menu of actions; closes on select, Escape or an outside press. */
export function Menu({ label, trigger, items, className, triggerClassName }: MenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useClickOutside(rootRef, () => setOpen(false), open)

  return (
    <div
      ref={rootRef}
      className={cn('relative', className)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        className={cn(
          'rounded-chip p-0.5 text-subtle transition-colors duration-150 hover:bg-raised hover:text-foreground',
          triggerClassName,
        )}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-6 z-50 min-w-[140px] rounded-card border border-panel-border bg-popover py-1 text-xs shadow-lg"
        >
          {items.map((item) => (
            <div key={item.label}>
              {item.separatorBefore && <div className="mx-2 my-1 border-t border-border/60" />}
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={(e) => {
                  e.stopPropagation()
                  setOpen(false)
                  item.onSelect()
                }}
                className={cn(
                  'flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors duration-150 hover:bg-hover disabled:opacity-40',
                  item.destructive ? 'text-danger' : 'text-text-3',
                )}
              >
                {item.icon && <item.icon className="h-3 w-3" />}
                {item.label}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
