import type { ReactNode } from 'react'

/** A keyboard key or short key combination, for hints like "/ commands". */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-sm border border-border-strong px-1.5 font-mono text-2xs text-muted-foreground">
      {children}
    </kbd>
  )
}
