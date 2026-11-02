import { useEffect, useRef } from 'react'

/** Overlays currently listening, oldest first. Only the last one acts on Escape. */
const listening: symbol[] = []

/**
 * Call `onEscape` when Escape is pressed, for the topmost overlay only: a confirmation
 * dialog over a drawer closes the dialog and leaves the drawer open. A control that uses
 * Escape for itself (closing its own suggestions, say) calls `preventDefault()` and the
 * overlay behind it stays. Listens only while `active`.
 */
export function useEscapeKey(onEscape: () => void, active = true): void {
  // Latest callback without re-subscribing on every render, which would reorder the stack.
  const callback = useRef(onEscape)
  callback.current = onEscape

  useEffect(() => {
    if (!active) return
    const id = Symbol('escape-listener')
    listening.push(id)
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return
      if (listening[listening.length - 1] === id) callback.current()
    }
    document.addEventListener('keydown', handler)
    return () => {
      document.removeEventListener('keydown', handler)
      listening.splice(listening.indexOf(id), 1)
    }
  }, [active])
}
