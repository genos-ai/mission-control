import { useResearchStore } from '@/stores/research'

const SIZE = 80
const STROKE = 6
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function CoverageRing() {
  const ratio = useResearchStore((s) => s.coverageRatio)
  const iteration = useResearchStore((s) => s.iteration)
  const maxIterations = useResearchStore((s) => s.maxIterations)
  const gapsRemaining = useResearchStore((s) => s.gapsRemaining)

  const pct = Math.round(ratio * 100)
  const offset = CIRCUMFERENCE * (1 - ratio)

  return (
    <div className="flex items-center gap-4">
      <svg width={SIZE} height={SIZE} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          className="text-muted/30"
        />
        {/* Progress ring */}
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="text-primary transition-all duration-500"
        />
      </svg>
      <div className="text-sm">
        <div className="text-2xl font-semibold text-foreground">{pct}%</div>
        <div className="text-xs text-muted-foreground">
          Iteration {iteration}/{maxIterations}
        </div>
        {gapsRemaining > 0 && (
          <div className="text-xs text-muted-foreground">
            {gapsRemaining} gap{gapsRemaining !== 1 ? 's' : ''} remaining
          </div>
        )}
      </div>
    </div>
  )
}
