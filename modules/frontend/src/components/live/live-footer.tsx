import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { useLiveRunStore } from '@/stores/live-run'

const STATUS_STYLES: Record<
  string,
  { variant: 'warning' | 'success' | 'destructive' | 'secondary'; label: string; pulse?: boolean }
> = {
  planning: { variant: 'warning', label: 'PLANNING', pulse: true },
  running: { variant: 'warning', label: 'RUNNING', pulse: true },
  success: { variant: 'success', label: 'SUCCESS' },
  failed: { variant: 'destructive', label: 'FAILED' },
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `${min}:${sec.toString().padStart(2, '0')}`
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
        <Badge
          variant={style.variant}
          className={`text-[10px] ${style.pulse ? 'animate-pulse' : ''}`}
        >
          {style.label}
        </Badge>
        <span className="text-muted-foreground/60">|</span>
        <span className="font-mono">{formatElapsed(elapsed)}</span>
      </div>
    </div>
  )
}
