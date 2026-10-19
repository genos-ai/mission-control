import type { ReactNode } from 'react'

/** A labelled block inside a detail panel. */
export function DetailSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-xs text-subtle">{label}</p>
      {children}
    </div>
  )
}
