import * as React from 'react'

import { cn } from '@/lib/cn'

export interface InputGroupProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Fixed text before the value, inside the same bordered field. */
  prefixLabel?: string
  /** Fixed text after the value, inside the same bordered field. */
  suffixLabel?: string
  /** Sets the prefix and the value in the mono face. */
  mono?: boolean
}

/** An Input with a fixed prefix and/or suffix inside one bordered field. All input props go to the input. */
const InputGroup = React.forwardRef<HTMLInputElement, InputGroupProps>(
  ({ prefixLabel, suffixLabel, mono, className, ...props }, ref) => (
    <div
      className={cn(
        'flex h-[38px] w-full items-center gap-1 rounded-md border border-border-strong bg-field px-3 text-md transition-colors focus-within:border-brand/60 focus-within:ring-2 focus-within:ring-brand/15',
        props.disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
    >
      {prefixLabel && <span className={cn('shrink-0 text-subtle', mono && 'font-mono')}>{prefixLabel}</span>}
      <input
        ref={ref}
        className={cn(
          'h-full min-w-0 flex-1 bg-transparent outline-none placeholder:text-subtle disabled:cursor-not-allowed',
          mono && 'font-mono',
        )}
        {...props}
      />
      {suffixLabel && <span className="shrink-0 text-xs text-subtle">{suffixLabel}</span>}
    </div>
  ),
)
InputGroup.displayName = 'InputGroup'

export { InputGroup }
