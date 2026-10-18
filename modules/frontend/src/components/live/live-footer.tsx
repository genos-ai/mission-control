import { useState, useEffect } from 'react'
import { StatusPill } from '@/components/ui/status-pill'
import { formatElapsed } from '@/lib/format-date'
import type { Tone } from '@/lib/status-tone'
import { useLiveRunStore } from '@/stores/live-run'

const STATUS_STYLES: Record<
  string,
  { tone: Tone; label: string; pulse?: boolean }
> = {
  planning: { tone: 'warning', label: 'PLANNING', pulse: true },
  running: { tone: 'warning', label: 'RUNNING', pulse: true },
  success: { tone: 'success', label: 'SUCCESS' },
  failed: { tone: 'danger', label: 'FAILED' },
}

export function LiveFooter() {
  const status = useLiveRunStore((s) => s.status)
  const totalCost = useLiveRunStore((s) => s.totalCost)
  const completedTasks = useLiveRunStore((s) => s.completedTasks)
  const totalTasks = useLiveRunStore((s) => s.totalTasks)
  const startedAt = useLiveRunStore((s) => s.startedAt)

  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!startedAt) return
    const tick = () => setElapsed(Date.now() - startedAt)
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [startedAt])

  const style = STATUS_STYLES[status] ?? STATUS_STYLES.planning

  return (
    <div className="flex items-center justify-between border-t bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
      <div className="flex items-center gap-4">
        <span className="font-mono">${totalCost.toFixed(4)}</span>
        <span className="text-muted-foreground/60">|</span>
        <span>
          {completedTasks}/{totalTasks || '?'} tasks
        </span>
      </div>

      <div className="flex items-center gap-4">
        <StatusPill tone={style.tone} pulse={style.pulse}>
          {style.label}
        </StatusPill>
        <span className="text-muted-foreground/60">|</span>
        <span className="font-mono">{formatElapsed(elapsed)}</span>
      </div>
    </div>
  )
}
