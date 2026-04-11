import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Returns a width value and a drag-handle onMouseDown handler.
 * Attach onMouseDown to a thin divider element at the panel's left edge.
 * The panel itself should use style={{ width }} instead of a fixed Tailwind width class.
 */
export function useResizable(defaultWidth: number, min = 160, max = 600) {
  const [width, setWidth] = useState(defaultWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return
      // Panel is on the right, so dragging left = wider
      const delta = startX.current - e.clientX
      setWidth(Math.min(max, Math.max(min, startWidth.current + delta)))
    }
    const onMouseUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [min, max])

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = width
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    e.preventDefault()
  }, [width])

  return { width, onMouseDown }
}
