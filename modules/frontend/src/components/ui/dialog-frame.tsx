import type { ReactNode } from 'react'

import { useEscapeKey } from '@/hooks/use-escape-key'
import { Panel } from '@/components/ui/panel'

export interface DialogFrameProps {
  /** Names the dialog for assistive technology. */
  title: string
  onCancel: () => void
  children: ReactNode
}

/** A centred modal: a dimmed backdrop that closes on click and on Escape, and the panel above it. */
export function DialogFrame({ title, onCancel, children }: DialogFrameProps) {
  useEscapeKey(onCancel)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-sm p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </Panel>
    </div>
  )
}
