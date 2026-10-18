import { useEffect, useRef, type RefObject } from 'react'

/**
 * Call `onOutside` when a mouse press lands outside `ref`'s element.
 * Listens only while `active`, so a closed popover costs nothing.
 */
export function useClickOutside(
  ref: RefObject<HTMLElement>,
  onOutside: () => void,
  active: boolean,
): void {
  // Latest callback without re-subscribing on every render.
  const callback = useRef(onOutside)
  callback.current = onOutside

  useEffect(() => {
    if (!active) return
    const handler = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) callback.current()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [ref, active])
}
