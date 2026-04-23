import { useResearchStore } from '@/stores/research'
import { Badge } from '@/components/ui/badge'
import { NarrativeFeed } from './narrative-feed'
import { SubQuestionTree } from './sub-question-tree'
import { CoverageRing } from './coverage-ring'
import { StreamingReport } from './streaming-report'
import { SourcePanel } from './source-panel'

/**
 * Three-panel research live view (Plan 40 §11.4).
 *
 * Overlay component that appears when a research loop is active.
 * Layout: Activity Feed | Workspace | Artifacts
 *
 * This is the reference implementation for the platform's mission
 * live experience pattern — future mission types will follow this layout.
 */
export function ResearchLiveView() {
  const isActive = useResearchStore((s) => s.isActive)
  const reportComplete = useResearchStore((s) => s.reportComplete)
  const query = useResearchStore((s) => s.query)
  const costUsd = useResearchStore((s) => s.costUsd)
  const iteration = useResearchStore((s) => s.iteration)
  const maxIterations = useResearchStore((s) => s.maxIterations)
  const totalSources = useResearchStore((s) => s.totalSources)
  const isSynthesizing = useResearchStore((s) => s.isSynthesizing)
  const depth = useResearchStore((s) => s.depth)

  // Don't render if no research is active or completed
  if (!isActive && !reportComplete) return null

  const phase = isSynthesizing
    ? 'Synthesizing'
    : isActive
      ? 'Researching'
      : 'Complete'

  return (
    <div className="flex h-full flex-col">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-4 py-2">
        <div className="flex items-center gap-3">
          <Badge
            variant={isActive ? 'warning' : 'success'}
            className={`text-[10px] ${isActive ? 'animate-pulse' : ''}`}
          >
            {phase}
          </Badge>
          <span className="text-sm font-medium text-foreground truncate max-w-md">
            {query}
          </span>
          <span className="text-xs text-muted-foreground">({depth})</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground font-mono">
          <span>Iter {iteration}/{maxIterations}</span>
          <span className="text-muted-foreground/40">|</span>
          <span>{totalSources} sources</span>
          <span className="text-muted-foreground/40">|</span>
          <span>${costUsd.toFixed(2)}</span>
        </div>
      </div>

      {/* Three-panel layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Activity Feed */}
        <div className="w-1/4 min-w-[200px] border-r border-border overflow-y-auto p-2">
          <NarrativeFeed />
        </div>

        {/* Center: Workspace */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="flex items-start gap-6 mb-4">
            <div className="flex-1">
              <SubQuestionTree />
            </div>
            <CoverageRing />
          </div>
          <StreamingReport />
        </div>

        {/* Right: Artifacts / Sources */}
        <div className="w-1/4 min-w-[200px] border-l border-border overflow-y-auto p-2">
          <SourcePanel />
        </div>
      </div>
    </div>
  )
}
