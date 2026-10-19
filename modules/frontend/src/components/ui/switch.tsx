import { cn } from '@/lib/cn'

export interface SwitchProps {
  checked: boolean
  onChange: (next: boolean) => void
  /** What the switch controls, for screen readers. */
  label: string
  disabled?: boolean
}

/** An on/off toggle. The knob is white in both themes. */
export function Switch({ checked, onChange, label, disabled = false }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-brand' : 'bg-border-strong',
      )}
    >
      <span
        className={cn(
          'absolute left-0.5 h-3 w-3 rounded-full bg-white transition-transform duration-150',
          checked && 'translate-x-3',
        )}
      />
    </button>
  )
}
