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
import {
  DragDropContext,
  Droppable,
  Draggable,
  type DropResult,
} from '@hello-pangea/dnd'
import {
  AlertTriangle,
  Brain,
  FileText,
  Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import {
  useMissionPlan,
  useRefinePlan,
  useReorderTasks,
  type MissionPlan,
  type PlanTaskStatus,
} from '@/hooks/use-mission-plan'
import { useWorkspaceStore } from '@/stores/workspace'
import type {
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
import { TaskCard, AddTaskForm, ShimmerCard } from './plan-board-task-card'
import { PlanTopBar, RefinePanel } from './plan-board-top-bar'

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
        <AlertTriangle className="h-6 w-6 text-destructive/60" />
        <p className="text-sm text-destructive/80">Failed to load plan</p>
        <p className="text-xs text-muted-foreground/60">{String(error)}</p>
      </div>
    )
  }

  if (!plan) return null

  const tasks = plan.task_plan_json?.tasks ?? []
  if (tasks.length === 0) {
    return <EmptyState onChat={() => navigate(`/missions/${id ?? missionId}/chat`)} plan={plan} />
  }

  // Join bodies ⋈ states ⋈ liveOverlay by task_id.
  const statesById: Record<string, import('@/hooks/use-mission-plan').PlanTaskState> = {}
  for (const s of plan.task_states) statesById[s.task_id] = s

  const joined: JoinedTask[] = tasks.map((body) => {
    const state = statesById[body.task_id] ?? null
    const overlay = liveOverlay[body.task_id]
    const effective: PlanTaskStatus =
      (overlay?.status as PlanTaskStatus) ??
      (state?.status as PlanTaskStatus) ??
      'proposed'
    return { body, state, effectiveStatus: effective }
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
  const [proposedOrder, setProposedOrder] = useState<string[] | null>(null)
  const refine = useRefinePlan(missionId)
  const reorderTasks = useReorderTasks(missionId)

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
    // Apply optimistic drag order for proposed column.
    if (proposedOrder) {
      const byId = new Map(out.proposed.map((t) => [t.body.task_id, t]))
      const ordered = proposedOrder
        .map((id) => byId.get(id))
        .filter((t): t is AnnotatedTask => t !== undefined)
      const orderedSet = new Set(proposedOrder)
      for (const t of out.proposed) {
        if (!orderedSet.has(t.body.task_id)) ordered.push(t)
      }
      out.proposed = ordered
    }
    // Sort Done with most recent first (newest runs at the top).
    out.done.sort((a, b) =>
      (b.state?.last_attempt_at ?? '').localeCompare(a.state?.last_attempt_at ?? ''),
    )
    return out
  }, [annotated, proposedOrder])

  function handleDragEnd(result: DropResult) {
    if (!result.destination) return
    if (result.source.droppableId !== 'proposed' || result.destination.droppableId !== 'proposed') return
    if (result.source.index === result.destination.index) return

    const ids = byColumn.proposed.map((t) => t.body.task_id)
    const [removed] = ids.splice(result.source.index, 1)
    ids.splice(result.destination.index, 0, removed)

    setProposedOrder(ids)
    reorderTasks.mutate(ids, {
      onSuccess: () => setProposedOrder(null),
      onError: () => {
        setProposedOrder(null)
        toast.error('Failed to reorder tasks')
      },
    })
  }

  return (
    <DragDropContext onDragEnd={handleDragEnd}>
      <div className="flex h-full min-h-0 flex-col">
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
        <BoardArea
          byColumn={byColumn}
          edges={edges}
          missionId={missionId}
          isRefining={refine.isPending}
        />
      </div>
    </DragDropContext>
  )
}

// ── Board area (columns + SVG dependency overlay) ────────────────────────

function BoardArea({
  byColumn,
  edges,
  missionId,
  isRefining,
}: {
  byColumn: Record<ColumnId, AnnotatedTask[]>
  edges: Edge[]
  missionId: string
  isRefining: boolean
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
    <div className="relative flex-1 overflow-auto">
      <div
        ref={innerRef}
        className="relative min-h-full min-w-[1040px] p-3"
      >
        {/* Dependency curves overlay */}
        <svg
          className="pointer-events-none absolute inset-0"
          width="100%"
          height="100%"
          aria-hidden
        >
          {edges.map((e, i) => {
            const from = rects[e.from]
            const to = rects[e.to]
            if (!from || !to) return null
            return (
              <path
                key={`${e.from}-${e.to}-${i}`}
                d={bezierPath(from, to)}
                stroke={edgeColor(e.state)}
                strokeWidth={1.5}
                fill="none"
              />
            )
          })}
        </svg>

        {/* Columns row */}
        <div className="relative z-10 flex items-start gap-3">
          {COLUMN_DEFS.map((def) => (
            <Column
              key={def.id}
              def={def}
              rows={byColumn[def.id]}
              missionId={missionId}
              registerRef={register}
              showShimmer={def.id === 'proposed' && isRefining}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Column ───────────────────────────────────────────────────────────────

function Column({
  def,
  rows,
  missionId,
  registerRef,
  showShimmer,
}: {
  def: import('./plan-board-types').ColumnDef
  rows: AnnotatedTask[]
  missionId: string
  registerRef: (taskId: string) => RefCallback<HTMLDivElement>
  showShimmer: boolean
}) {
  const parallelism = def.id === 'running' && rows.length > 1
  const isProposed = def.id === 'proposed'
  const [addingTask, setAddingTask] = useState(false)

  const cards = rows.map((row, index) =>
    isProposed ? (
      <Draggable key={row.body.task_id} draggableId={row.body.task_id} index={index}>
        {(provided, snapshot) => (
          <TaskCard
            row={row}
            missionId={missionId}
            cardRef={registerRef(row.body.task_id)}
            dragInnerRef={provided.innerRef}
            draggableProps={provided.draggableProps}
            dragHandleProps={provided.dragHandleProps}
            isDragging={snapshot.isDragging}
          />
        )}
      </Draggable>
    ) : (
      <TaskCard
        key={row.body.task_id}
        row={row}
        missionId={missionId}
        cardRef={registerRef(row.body.task_id)}
      />
    ),
  )

  return (
    <div className="flex min-w-[260px] max-w-[320px] flex-1 flex-col">
      <div className="mb-2 flex items-center gap-2 px-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {def.label}
        </span>
        <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">
          {rows.length}
        </Badge>
        {parallelism && (
          <span
            className="flex items-center gap-0.5 text-[9px] text-amber-400"
            title={`${rows.length} agents running in parallel`}
          >
            <Zap className="h-2.5 w-2.5 fill-amber-400" />
            {rows.length}
          </span>
        )}
      </div>
      {isProposed ? (
        <>
          <Droppable droppableId="proposed">
            {(provided, snapshot) => (
              <div
                ref={provided.innerRef}
                {...provided.droppableProps}
                className={cn(
                  'space-y-2 rounded-lg p-2 min-h-[60px] transition-colors',
                  snapshot.isDraggingOver ? 'bg-primary/5 ring-1 ring-inset ring-primary/20' : 'bg-muted/30',
                )}
              >
                {showShimmer && <ShimmerCard />}
                {cards}
                {provided.placeholder}
                {rows.length === 0 && !showShimmer && !addingTask && (
                  <div className="flex h-16 items-center justify-center rounded border border-dashed border-border/30 text-[10px] text-muted-foreground/30">
                    empty
                  </div>
                )}
              </div>
            )}
          </Droppable>
          {addingTask ? (
            <AddTaskForm
              missionId={missionId}
              onDone={() => setAddingTask(false)}
            />
          ) : (
            <button
              onClick={() => setAddingTask(true)}
              className="mt-1.5 flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] text-muted-foreground/50 hover:bg-muted/40 hover:text-muted-foreground transition-colors"
            >
              <span className="text-base leading-none">+</span>
              Add task
            </button>
          )}
        </>
      ) : (
        <div className="space-y-2 rounded-lg bg-muted/30 p-2 min-h-[60px]">
          {showShimmer && <ShimmerCard />}
          {cards}
          {rows.length === 0 && !showShimmer && (
            <div className="flex h-16 items-center justify-center rounded border border-dashed border-border/30 text-[10px] text-muted-foreground/30">
              empty
            </div>
          )}
        </div>
      )}
    </div>
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
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <FileText className="h-7 w-7 text-primary/60" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">No plan yet</p>
        <p className="max-w-[360px] text-xs text-muted-foreground/70">
          Ask the Director what you want to work on — they'll propose a plan
          you can review and approve here.
        </p>
      </div>
      <Button size="sm" onClick={onChat} className="gap-1.5">
        <Brain className="h-3.5 w-3.5" />
        Talk to the Director
      </Button>
      {plan.gate_mode && (
        <p className="text-[10px] text-muted-foreground/40">
          Plan v{plan.version} · gate_mode: {plan.gate_mode}
        </p>
      )}
    </div>
  )
}

// ── StatusIcon (re-exported from task-card for use in Column if needed) ──

// ── Graph helpers ────────────────────────────────────────────────────────

function computeAnnotated(joined: JoinedTask[]): AnnotatedTask[] {
  const byId = new Map(joined.map((j) => [j.body.task_id, j]))
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
    const blockingDeps = j.body.dependencies.filter((depId) => {
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
