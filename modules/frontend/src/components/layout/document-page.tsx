import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

/**
 * The body of a "document" screen: a centred column that scrolls with the page.
 * Workspace screens (chat, plan, run live) lay out their own floating panels instead.
 */
export function DocumentPage({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('mx-auto flex w-full max-w-[1160px] flex-col gap-3 px-8 pb-10 pt-1', className)}>
      {children}
    </div>
  )
}
