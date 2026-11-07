import type { ReactNode } from 'react'

import { useEscapeKey } from '@/hooks/use-escape-key'
import { Panel } from '@/components/ui/panel'

const WIDTHS = { sm: 'max-w-sm', md: 'max-w-md' } as const

export interface DialogFrameProps {
  /** Names the dialog for assistive technology. */
  title: string
  onCancel: () => void
  /** sm for a confirmation, md for a form. */
  width?: keyof typeof WIDTHS
  /** Whether a click on the backdrop closes the dialog. Turn it off where a stray click would discard typed input. */
  closeOnBackdrop?: boolean
  children: ReactNode
}

/** A centred modal: a dimmed backdrop, the panel above it, and Escape to close. */
export function DialogFrame({
  title,
  onCancel,
  width = 'sm',
  closeOnBackdrop = true,
  children,
}: DialogFrameProps) {
  useEscapeKey(onCancel)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm"
      onClick={closeOnBackdrop ? onCancel : undefined}
    >
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${WIDTHS[width]} p-5 shadow-lg`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </Panel>
    </div>
  )
}
