/**
 * IdleOverview — center panel when no run is active.
 *
 * Shows: mission brief, last 5 runs with status/cost/duration,
 * and any artifacts cached from the previous run.
 */

import { useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import {
  Play,
  CheckCircle,
  XCircle,
  Clock,
  Package,
  ChevronDown,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { RunModal } from '@/components/mission/run-modal'
import { useMission } from '@/hooks/use-missions'
import { useExecutions } from '@/hooks/use-executions'
import { useWorkspaceStore } from '@/stores/workspace'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/lib/constants'
import type { ExecutionRecord } from '@/types'

export function IdleOverview({ missionId }: { missionId: string }) {
  const navigate = useNavigate()
  const [showRunModal, setShowRunModal] = useState(false)

  const { data: mission, isLoading: missionLoading } = useMission(missionId)
  const { data: execData, isLoading: execLoading } = useExecutions({
    mission_id: missionId,
    limit: 5,
  })
  const artifacts = useWorkspaceStore((s) => s.artifacts)

  const runs = execData?.executions ?? []

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-xl space-y-6">

        {/* Mission brief */}
        <div className="rounded-lg border bg-card p-4">
          {missionLoading ? (
            <Spinner className="h-4 w-4" />
          ) : (
            <>
              <h2 className="mb-1 text-sm font-semibold">{mission?.name}</h2>
              {mission?.brief ? (
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {mission.brief}
                </p>
              ) : (
                <p className="text-xs italic text-muted-foreground/50">
                  No mission brief set.
                </p>
              )}
              <Button
                size="sm"
                className="mt-3 h-7 text-xs"
                onClick={() => setShowRunModal(true)}
              >
                <Play className="mr-1.5 h-3 w-3" />
                Start Run
              </Button>
            </>
          )}
        </div>

        {/* Recent runs */}
        <div>
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Recent Runs
          </h3>
          {execLoading ? (
            <div className="flex justify-center py-4"><Spinner className="h-4 w-4" /></div>
          ) : runs.length === 0 ? (
            <p className="text-xs text-muted-foreground/60">No runs yet.</p>
          ) : (
            <div className="space-y-1.5">
              {runs.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  missionId={missionId}
                  onNavigate={() => navigate(ROUTES.MISSION_RUN_LIVE(missionId, run.id))}
                />
              ))}
            </div>
          )}
        </div>

        {/* Pinned artifacts from last session */}
        {artifacts.length > 0 && (
          <div>
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Last Run Artifacts
            </h3>
            <div className="space-y-1.5">
              {artifacts.slice(0, 3).map((a) => (
                <details key={a.id} className="group rounded border border-violet-500/15 bg-violet-500/5 p-2.5 text-xs">
                  <summary className="flex cursor-pointer list-none items-center gap-2">
                    <Package className="h-3 w-3 shrink-0 text-violet-400" />
                    <span className="flex-1 font-medium">{a.title}</span>
                    <Badge variant="outline" className="h-3.5 text-[9px]">{a.artifactType}</Badge>
                    <ChevronDown className="h-3 w-3 text-muted-foreground transition-transform group-open:rotate-180" />
                  </summary>
                  <div className="mt-2 border-t border-violet-500/15 pt-2">
                    <MarkdownRenderer content={a.content} className="text-xs" />
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}
      </div>

      {showRunModal && (
        <RunModal
          missionId={missionId}
          onClose={() => setShowRunModal(false)}
          onStarted={(executionId) => {
            setShowRunModal(false)
            navigate(ROUTES.MISSION_RUN_LIVE(missionId, executionId))
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single run row
// ---------------------------------------------------------------------------

function RunRow({
  run,
  missionId: _missionId,
  onNavigate,
}: {
  run: ExecutionRecord
  missionId: string
  onNavigate: () => void
}) {
  const ok = run.status === 'completed'
  const failed = run.status === 'failed' || run.status === 'cancelled' || run.status === 'timed_out'
  const running = run.status === 'running' || run.status === 'pending'

  const dur =
    run.started_at && run.completed_at
      ? Math.round(
          (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000,
        )
      : null

  return (
    <button
      onClick={onNavigate}
      className="flex w-full items-center gap-2.5 rounded border bg-card px-3 py-2 text-xs transition-colors hover:bg-accent"
    >
      {ok ? (
        <CheckCircle className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
      ) : failed ? (
        <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
      ) : (
        <Clock className="h-3.5 w-3.5 shrink-0 animate-pulse text-amber-400" />
      )}

      <Badge
        variant={ok ? 'success' : failed ? 'destructive' : 'secondary'}
        className="h-4 shrink-0 text-[9px]"
      >
        {run.status}
      </Badge>

      <span className={cn('flex-1 text-left truncate text-muted-foreground', running && 'text-amber-400')}>
        {run.started_at
          ? formatDistanceToNow(new Date(run.started_at), { addSuffix: true })
          : formatDistanceToNow(new Date(run.created_at), { addSuffix: true })}
      </span>

      {run.total_cost_usd > 0 && (
        <span className="shrink-0 text-muted-foreground">
          ${run.total_cost_usd.toFixed(4)}
        </span>
      )}
      {dur != null && (
        <span className="shrink-0 text-muted-foreground">{dur}s</span>
      )}
    </button>
  )
}
