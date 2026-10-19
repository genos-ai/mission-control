import { cn } from '@/lib/cn'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
  /** Optional count shown after the label. */
  count?: number
  /** Tooltip explaining the option. */
  title?: string
}

export interface SegmentedProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: SegmentedOption<T>[]
  /** Accessible name for the group. */
  label: string
  disabled?: boolean
}

/** A small single-choice switch: a row of options with the chosen one raised. */
export function Segmented<T extends string>({ value, onChange, options, label, disabled = false }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="flex shrink-0 rounded-md bg-raised p-0.5">
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            title={option.title}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'flex h-6 items-center gap-1.5 whitespace-nowrap rounded-chip px-2.5 text-xs transition-colors duration-150 disabled:pointer-events-none',
              selected ? 'bg-panel text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {option.label}
            {option.count !== undefined && <span className="font-mono text-2xs text-subtle">{option.count}</span>}
          </button>
        )
      })}
    </div>
  )
}
