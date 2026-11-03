/**
 * PlanBoard — horizontal 4-column kanban over the Plan 42 backend.
 *
 * See plan-board-types.ts, plan-board-task-card.tsx, and
 * plan-board-top-bar.tsx for the extracted helpers, card components,
 * and top-bar/refine-panel components.
 */

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefCallback,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Brain, FileText, Zap } from 'lucide-react'
import { cn } from '@/lib/cn'
import { taskTone, type StatusStyle } from '@/lib/status-tone'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { StatusIcon } from '@/components/ui/status-icon'
import {
  useMissionPlan,
  useRefinePlan,
  type MissionPlan,
  type PlanTaskStatus,
} from '@/hooks/use-mission-plan'
import { useWorkspaceStore } from '@/stores/workspace'
import type {
  ColumnDef,
  ColumnId,
  AnnotatedTask,
  JoinedTask,
  Rect,
  Edge,
} from './plan-board-types'
import {
  COLUMN_DEFS,
  columnFor,
  edgeColor,
  bezierPath,
  computeEdges,
} from './plan-board-types'
import { AddTask } from './plan-board-add-task'
import { TaskCard, ShimmerCard } from './plan-board-task-card'
import { TaskDetailPanel } from './plan-board-detail-panel'
import { PlanTopBar, RefinePanel } from './plan-board-top-bar'

// Each column is headed by the style of the status it stands for.
const COLUMN_STYLE: Record<ColumnId, StatusStyle> = {
  proposed: taskTone.proposed,
  approved: taskTone.approved,
  running: taskTone.running,
  done: taskTone.completed,
}

// A column narrower than this would clip its cards. With all four populated the board needs
// 4 x 250px plus the gutters, the width it always had; empty columns give theirs back.
const COLUMN_MIN_WIDTH = '250px'
const RAIL_WIDTH = '44px'

/** Proposed always stays open: it holds the add-task row, and new tasks enter there. */
function isCollapsed(id: ColumnId, rows: AnnotatedTask[]): boolean {
  return id !== 'proposed' && rows.length === 0
}

// ── Board root ───────────────────────────────────────────────────────────

export function PlanBoard({ missionId }: { missionId: string }) {
  const { data: plan, isLoading, error } = useMissionPlan(missionId)
  const liveOverlay = useWorkspaceStore((s) => s.liveTaskOverlay)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-5 w-5" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8">
        <AlertTriangle className="h-6 w-6 text-danger" />
        <p className="text-sm text-danger">Failed to load plan</p>
        <p className="text-xs text-subtle">{String(error)}</p>
      </div>
    )
  }

  if (!plan) return null

  const tasks = plan.tasks ?? []
  if (tasks.length === 0) {
    return <EmptyState onChat={() => navigate(`/missions/${id ?? missionId}/chat`)} plan={plan} />
  }

  // Apply live overlay to each task's status.
  const joined: JoinedTask[] = tasks.map((task) => {
    const overlay = liveOverlay[task.id]
    const effective: PlanTaskStatus =
      (overlay?.status as PlanTaskStatus) ?? task.status
    return { task, effectiveStatus: effective }
  })

  return <PlanBoardInner plan={plan} missionId={missionId} joined={joined} />
}

// ── Board inner (stateful, grouped) ──────────────────────────────────────

function PlanBoardInner({
  plan,
  missionId,
  joined,
}: {
  plan: MissionPlan
  missionId: string
  joined: JoinedTask[]
}) {
  const [refineOpen, setRefineOpen] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const refine = useRefinePlan(missionId)

  const selectedTask = selectedTaskId
    ? joined.find((j) => j.task.id === selectedTaskId)?.task ?? null
    : null

  const annotated = useMemo(() => computeAnnotated(joined), [joined])
  const edges = useMemo(() => computeEdges(joined), [joined])

  const byColumn = useMemo(() => {
    const out: Record<ColumnId, AnnotatedTask[]> = {
      proposed: [],
      approved: [],
      running: [],
      done: [],
    }
    for (const a of annotated) {
      out[columnFor(a.effectiveStatus)].push(a)
    }
    // Sort Done with most recent first (newest runs at the top).
    out.done.sort((a, b) =>
      (b.task.last_attempt_at ?? '').localeCompare(a.task.last_attempt_at ?? ''),
    )
    return out
  }, [annotated])

  return (
    <div className="flex h-full min-h-0 flex-col gap-gutter px-2 pb-2">
      <PlanTopBar
        plan={plan}
        missionId={missionId}
        joined={joined}
        onToggleRefine={() => setRefineOpen((v) => !v)}
        refineOpen={refineOpen}
      />
      {refineOpen && (
        <RefinePanel refine={refine} onDone={() => setRefineOpen(false)} />
      )}
      <div className="flex min-h-0 flex-1 gap-gutter">
        <BoardArea
          byColumn={byColumn}
          edges={edges}
          missionId={missionId}
          isRefining={refine.isPending}
          onSelectTask={setSelectedTaskId}
        />
        {selectedTask && (
          <TaskDetailPanel
            task={selectedTask}
            onClose={() => setSelectedTaskId(null)}
          />
        )}
      </div>
    </div>
  )
}

// ── Board area (columns + SVG dependency overlay) ────────────────────────

function BoardArea({
  byColumn,
  edges,
  missionId,
  isRefining,
  onSelectTask,
}: {
  byColumn: Record<ColumnId, AnnotatedTask[]>
  edges: Edge[]
  missionId: string
  isRefining: boolean
  onSelectTask: (taskId: string) => void
}) {
  const innerRef = useRef<HTMLDivElement | null>(null)
  const cardRefs = useRef<Map<string, HTMLDivElement | null>>(new Map())
  const [rects, setRects] = useState<Record<string, Rect>>({})

  function register(taskId: string): RefCallback<HTMLDivElement> {
    return (el) => {
      if (el) cardRefs.current.set(taskId, el)
      else cardRefs.current.delete(taskId)
    }
  }

  function measure() {
    const inner = innerRef.current
    if (!inner) return
    const innerRect = inner.getBoundingClientRect()
    const next: Record<string, Rect> = {}
    cardRefs.current.forEach((el, id) => {
      if (!el) return
      const r = el.getBoundingClientRect()
      next[id] = {
        left: r.left - innerRect.left,
        top: r.top - innerRect.top,
        right: r.right - innerRect.left,
        bottom: r.bottom - innerRect.top,
        width: r.width,
        height: r.height,
      }
    })
    setRects(next)
  }

  // Remeasure on every data-driven render (layout may have shifted).
  useLayoutEffect(() => {
    measure()
  }, [byColumn])

  // Remeasure when the board container resizes (window resize, etc).
  useEffect(() => {
    const inner = innerRef.current
    if (!inner) return
    const ro = new ResizeObserver(() => measure())
    ro.observe(inner)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="relative min-w-0 flex-1 overflow-auto">
      <div
        ref={innerRef}
        className="relative grid min-h-full items-stretch gap-gutter"
        style={{
          gridTemplateColumns: COLUMN_DEFS.map((def) =>
            isCollapsed(def.id, byColumn[def.id]) ? RAIL_WIDTH : `minmax(${COLUMN_MIN_WIDTH}, 1fr)`,
          ).join(' '),
        }}
      >
        {COLUMN_DEFS.map((def) => (
          <Column
            key={def.id}
            def={def}
            rows={byColumn[def.id]}
            collapsed={isCollapsed(def.id, byColumn[def.id])}
            missionId={missionId}
            registerRef={register}
            showShimmer={def.id === 'proposed' && isRefining}
            onSelectTask={onSelectTask}
          />
        ))}

        {/* Dependency curves, drawn over the panels (which are opaque). */}
        <svg className="pointer-events-none absolute inset-0 z-20" width="100%" height="100%" aria-hidden>
          {edges.map((e, i) => {
            const from = rects[e.from]
            const to = rects[e.to]
            if (!from || !to) return null
            return (
              <path
                key={`${e.from}-${e.to}-${i}`}
                d={bezierPath(from, to)}
                style={{ stroke: edgeColor(e.state) }}
                strokeWidth={1.5}
                fill="none"
              />
            )
          })}
        </svg>
      </div>
    </div>
  )
}

// ── Column ───────────────────────────────────────────────────────────────

function Column({
  def,
  rows,
  collapsed,
  missionId,
  registerRef,
  showShimmer,
  onSelectTask,
}: {
  def: ColumnDef
  rows: AnnotatedTask[]
  collapsed: boolean
  missionId: string
  registerRef: (taskId: string) => RefCallback<HTMLDivElement>
  showShimmer: boolean
  onSelectTask: (taskId: string) => void
}) {
  const parallelism = def.id === 'running' && rows.length > 1

  if (collapsed) {
    return (
      <Panel
        className="flex min-w-0 flex-col items-center gap-2 px-1 py-3"
        role="group"
        aria-label={`${def.label}, no tasks`}
      >
        <StatusIcon {...COLUMN_STYLE[def.id]} className="h-3.5 w-3.5 animate-none" />
        <span className="font-mono text-xs text-subtle">0</span>
        <span className="text-sm font-medium text-subtle [writing-mode:vertical-rl]">{def.label}</span>
      </Panel>
    )
  }

  return (
    <Panel className="flex min-w-0 flex-col gap-2 px-2.5 py-3">
      <div className="flex items-center gap-2 px-1 pb-1">
        <StatusIcon
          {...COLUMN_STYLE[def.id]}
          className={cn('h-3.5 w-3.5', def.id === 'running' && rows.length === 0 && 'animate-none')}
        />
        <span className="text-sm font-medium">{def.label}</span>
        <span className="font-mono text-xs text-subtle">{rows.length}</span>
        {parallelism && (
          <span
            className="flex items-center gap-0.5 font-mono text-2xs text-warning"
            title={`${rows.length} agents running in parallel`}
          >
            <Zap className="h-2.5 w-2.5 fill-warning" />
            {rows.length}
          </span>
        )}
      </div>
      {showShimmer && <ShimmerCard />}
      {rows.map((row) => (
        <TaskCard
          key={row.task.id}
          row={row}
          missionId={missionId}
          cardRef={registerRef(row.task.id)}
          onSelect={onSelectTask}
        />
      ))}
      {rows.length === 0 && !showShimmer && (
        <div className="flex h-12 items-center justify-center text-xs text-faint">empty</div>
      )}
      {/* New tasks always enter as proposed, so only that column offers adding one. */}
      {def.id === 'proposed' && <AddTask missionId={missionId} />}
    </Panel>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────

function EmptyState({
  onChat,
  plan,
}: {
  onChat: () => void
  plan: MissionPlan
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <IconTile icon={FileText} tone="brand" size="lg" />
      <div className="space-y-1">
        <p className="text-md">No plan yet</p>
        <p className="max-w-[360px] text-sm text-subtle">
          Ask the Director what you want to work on — they'll propose a plan
          you can review and approve here.
        </p>
      </div>
      <Button onClick={onChat}>
        <Brain className="h-3.5 w-3.5" />
        Talk to the Director
      </Button>
      {plan.gate_mode && (
        <p className="font-mono text-2xs text-faint">
          Plan v{plan.version} · gate_mode: {plan.gate_mode}
        </p>
      )}
    </div>
  )
}

// ── Graph helpers ────────────────────────────────────────────────────────

function computeAnnotated(joined: JoinedTask[]): AnnotatedTask[] {
  const byId = new Map(joined.map((j) => [j.task.id, j]))
  return joined.map((j) => {
    // Cards already running or past are never rendered as "blocked".
    const preRun =
      j.effectiveStatus === 'proposed' ||
      j.effectiveStatus === 'approved' ||
      j.effectiveStatus === 'queued'
    if (!preRun) {
      return { ...j, blocked: false, blockingDeps: [] }
    }
    // Dep is "met" if it's completed or skipped; anything else (pending,
    // running, failed, cancelled) means the dependent can't run yet.
    const blockingDeps = j.task.dependencies.filter((depId) => {
      const dep = byId.get(depId)
      if (!dep) return false // unknown dep → don't mark blocked
      return (
        dep.effectiveStatus !== 'completed' &&
        dep.effectiveStatus !== 'skipped'
      )
    })
    return { ...j, blocked: blockingDeps.length > 0, blockingDeps }
  })
}
