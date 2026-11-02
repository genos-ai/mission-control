import { Loader2 } from 'lucide-react'

import { cn } from '@/lib/cn'

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-4 w-4 animate-spin text-subtle motion-reduce:animate-none', className)} />
}

/** Fills the viewport while the app decides what to show, such as restoring a session. */
export function FullPageSpinner() {
  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <Spinner className="h-8 w-8" />
    </div>
  )
}
