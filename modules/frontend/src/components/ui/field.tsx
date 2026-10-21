import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

export interface FieldProps {
  label: string
  /** The id of the control the label names. */
  htmlFor?: string
  /** Quiet text after the label, e.g. "optional". */
  note?: string
  /** Help text under the control. */
  hint?: ReactNode
  /** Replaces the hint, in the danger colour. */
  error?: ReactNode
  /** The id the hint or error carries, for the control's `aria-describedby`. */
  describedById?: string
  children: ReactNode
}

/** A labelled form control with its help text or error. */
export function Field({ label, htmlFor, note, hint, error, describedById, children }: FieldProps) {
  const message = error ?? hint
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-text-3">
        {label}
        {note && <span className="ml-1.5 font-normal text-subtle">{note}</span>}
      </label>
      {children}
      {message && (
        <p id={describedById} className={cn('text-xs', error ? 'text-danger' : 'text-subtle')}>
          {message}
        </p>
      )}
    </div>
  )
}
