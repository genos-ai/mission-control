import { useResearchStore } from '@/stores/research'
import { Panel } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
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

  const phase = isSynthesizing ? 'Synthesizing' : isActive ? 'Researching' : 'Complete'

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-gutter">
      <Panel className="flex shrink-0 items-center justify-between gap-4 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <StatusPill tone={isActive ? 'warning' : 'success'} pulse={isActive}>
            {phase}
          </StatusPill>
          <span className="max-w-md truncate text-sm font-medium text-foreground">{query}</span>
          <span className="text-xs text-subtle">({depth})</span>
        </div>
        <div className="flex shrink-0 items-center gap-3 font-mono text-xs text-muted-foreground">
          <span>
            Iter {iteration}/{maxIterations}
          </span>
          <span>{totalSources} sources</span>
          <span>${costUsd.toFixed(2)}</span>
        </div>
      </Panel>

      <div className="flex min-h-0 flex-1 gap-gutter">
        {/* Left: Activity Feed */}
        <Panel className="w-1/4 min-w-[200px] overflow-y-auto p-2">
          <NarrativeFeed />
        </Panel>

        {/* Center: Workspace */}
        <Panel className="min-w-0 flex-1 overflow-y-auto p-4">
          <div className="mb-4 flex items-start gap-6">
            <div className="flex-1">
              <SubQuestionTree />
            </div>
            <CoverageRing />
          </div>
          <StreamingReport />
        </Panel>

        {/* Right: Artifacts / Sources */}
        <Panel className="w-1/4 min-w-[200px] overflow-y-auto p-2">
          <SourcePanel />
        </Panel>
      </div>
    </div>
  )
}
