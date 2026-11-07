import * as React from 'react'
import { cn } from '@/lib/cn'

// The form field look, shared with Input: a bordered, filled box with a brand focus ring.
const FIELD =
  'border border-border-strong bg-field outline-none transition-colors focus:border-brand/60 focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-50'

const FIELD_SIZES = {
  md: 'flex h-[38px] w-full rounded-md px-3 text-md',
  sm: 'flex h-8 w-full rounded-md px-2 text-xs',
  xs: 'h-7 rounded-chip px-2 text-xs',
} as const

// Selects that sit in a bar of controls rather than in a form.
const BARE_VARIANTS = {
  toolbar:
    'h-7 max-w-[200px] rounded-control border border-panel-border bg-raised px-2 text-xs text-muted-foreground outline-none transition-colors hover:text-foreground focus:border-brand/60',
  pill: 'h-6 max-w-[260px] appearance-none truncate rounded-full bg-raised pl-2.5 pr-6 text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
} as const

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  /** `field` for a form control (sized by `size`), `toolbar` and `pill` for a select in a bar of controls. */
  variant?: 'field' | 'toolbar' | 'pill'
  /** Height and type size of a `field`: md for forms, sm for dense panels, xs for inline rows. */
  size?: keyof typeof FIELD_SIZES
}

/** A native select, styled once. Pass `className` only to adjust the layout (width, flex), not the look. */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ variant = 'field', size = 'md', className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        variant === 'field' ? [FIELD, FIELD_SIZES[size]] : BARE_VARIANTS[variant],
        className,
      )}
      {...props}
    />
  ),
)
Select.displayName = 'Select'

export { Select }
