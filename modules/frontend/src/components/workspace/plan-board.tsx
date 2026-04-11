/**
 * PlanBoard — horizontal 4-column kanban over the Plan 42 backend.
 *
 * Reads the persistent plan from `GET /missions/:id/plan`, joins
 * `task_plan_json.tasks[]` bodies with `task_states[]` keyed by string
 * task_id, and overlays in-flight status from `workspaceStore.liveTaskOverlay`
 * (populated by plan.step.* SSE events — transient, durable truth lives in
 * plan_task_states).
 *
 * Columns and their source statuses:
 *
 *   Proposed  ← proposed                              (needs human decision)
 *   Approved  ← approved, queued                      (ready to dispatch)
 *   Running   ← running                               (live)
 *   Done      ← completed, failed, skipped, cancelled (terminal)
 *
 * Dependency curves: SVG cubic Beziers overlay the board, connecting the
 * right edge of a blocking card to the left edge of a dependent card.
 * Colors track blocker status: grey (pending), amber (running), faded
 * green (completed/skipped), red (failed/cancelled).
 *
 * A card in a pre-run column whose dependencies aren't yet completed is
 * rendered "blocked" — dimmed with a 🔒 label listing the blocking deps.
 *
 * Top bar: plan version, autonomy (gate_mode) selector, cumulative-budget
 * bar, Refine (opens inline RefinePanel → /plan/refine), Run N approved
 * (calls /plan/dispatch).
 *
 * Empty state: CTA to chat with the Director so they can propose a plan.
 *
 * Out of scope for this rewrite (tracked as follow-ups):
 *   - Drag-to-reorder within the Proposed column (needs @dnd-kit)
 *   - Layout/slide animations between columns (needs framer-motion)
 *   - Right-click → Edit / Reassign / Cancel on cards
 *   - "+ Add task" prompt at the bottom of Proposed
 *   - Live tool-call preview on Running cards
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
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Check,
  X,
  Play,
  Sparkles,
  Brain,
  FileText,
  Circle,
  Clock,
  AlertTriangle,
  Lock,
  Zap,
  Wrench,
  ChevronDown,
  ChevronRight,
  GripVertical,
  MoreVertical,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import {
  useMissionPlan,
  useRefinePlan,
  useApproveTask,
  useRejectTask,
  useRetryTask,
  useDispatchApproved,
  useUpdatePlan,
  useReorderTasks,
  useAddPlanTask,
  type MissionPlan,
  type PlanTaskBody,
  type PlanTaskState,
  type PlanTaskStatus,
  type GateMode,
} from '@/hooks/use-mission-plan'
import { useTeam } from '@/hooks/use-team'
import { useWorkspaceStore } from '@/stores/workspace'

// ── Types + column layout ────────────────────────────────────────────────

type ColumnId = 'proposed' | 'approved' | 'running' | 'done'

interface ColumnDef {
  id: ColumnId
  label: string
  statuses: PlanTaskStatus[]
}

const COLUMN_DEFS: ColumnDef[] = [
  { id: 'proposed', label: 'Proposed', statuses: ['proposed'] },
  { id: 'approved', label: 'Approved', statuses: ['approved', 'queued'] },
  { id: 'running', label: 'Running', statuses: ['running'] },
  { id: 'done', label: 'Done', statuses: ['completed', 'failed', 'skipped', 'cancelled'] },
]

function columnFor(status: PlanTaskStatus): ColumnId {
  for (const def of COLUMN_DEFS) {
    if (def.statuses.includes(status)) return def.id
  }
  return 'proposed'
}

/** One task body + its persistent state, with live-overlay applied. */
interface JoinedTask {
  body: PlanTaskBody
  state: PlanTaskState | null
  /** Overlay status wins over durable state when present. */
  effectiveStatus: PlanTaskStatus
}

/** JoinedTask with computed blocked-by-dependency info. */
interface AnnotatedTask extends JoinedTask {
  blocked: boolean
  blockingDeps: string[]
}

interface Rect {
  left: number
  top: number
  right: number
  bottom: number
  width: number
  height: number
}

interface Edge {
  from: string
  to: string
  state: 'grey' | 'amber' | 'green' | 'failed'
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
  const statesById: Record<string, PlanTaskState> = {}
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

// ── Top bar ──────────────────────────────────────────────────────────────

function PlanTopBar({
  plan,
  missionId,
  joined,
  onToggleRefine,
  refineOpen,
}: {
  plan: MissionPlan
  missionId: string
  joined: JoinedTask[]
  onToggleRefine: () => void
  refineOpen: boolean
}) {
  const updatePlan = useUpdatePlan(missionId)
  const dispatch = useDispatchApproved(missionId)

  const approvedCount = joined.filter(
    (j) => j.effectiveStatus === 'approved' || j.effectiveStatus === 'queued',
  ).length

  const budgetPct =
    plan.budget_usd_ceiling && plan.budget_usd_ceiling > 0
      ? Math.min(100, (plan.total_spent_usd / plan.budget_usd_ceiling) * 100)
      : 0

  async function handleGateMode(mode: GateMode) {
    try {
      await updatePlan.mutateAsync({ gate_mode: mode })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update gate mode')
    }
  }

  async function handleDispatch() {
    try {
      const result = await dispatch.mutateAsync()
      toast.success(
        `Run ${result.outcome_status} — $${result.total_cost_usd.toFixed(4)}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Dispatch failed')
    }
  }

  return (
    <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Plan
      </span>
      <Badge variant="secondary" className="h-4 text-[9px]">v{plan.version}</Badge>

      <div className="relative">
        <select
          value={plan.gate_mode ?? 'interactive'}
          onChange={(e) => handleGateMode(e.target.value as GateMode)}
          disabled={updatePlan.isPending}
          className="h-6 appearance-none rounded border bg-transparent pl-2 pr-6 text-[10px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          title="Autonomy mode (Plan 42 §10.4)"
        >
          <option value="off">off — fully autonomous</option>
          <option value="interactive">interactive — human in loop</option>
          <option value="ai_assisted">ai_assisted — AI in loop</option>
          <option value="autonomous">autonomous — unattended</option>
        </select>
      </div>

      {plan.budget_usd_ceiling != null && plan.budget_usd_ceiling > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] tabular-nums text-muted-foreground">
            ${plan.total_spent_usd.toFixed(2)} / ${plan.budget_usd_ceiling.toFixed(2)}
          </span>
          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                budgetPct > 80
                  ? 'bg-destructive'
                  : budgetPct > 50
                    ? 'bg-amber-500'
                    : 'bg-emerald-500',
              )}
              style={{ width: `${budgetPct}%` }}
            />
          </div>
        </div>
      )}

      <div className="ml-auto flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          className={cn(
            'h-6 gap-1 px-2 text-[11px]',
            refineOpen && 'bg-accent text-foreground',
          )}
          onClick={onToggleRefine}
          title="Refine plan via Planning Agent"
        >
          <Sparkles className="h-3 w-3" />
          Refine
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={handleDispatch}
          disabled={dispatch.isPending || approvedCount === 0}
          title={
            approvedCount === 0
              ? 'Approve tasks before running'
              : `Run ${approvedCount} approved task${approvedCount === 1 ? '' : 's'}`
          }
        >
          {dispatch.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          Run {approvedCount > 0 ? approvedCount : ''}
        </Button>
      </div>
    </div>
  )
}

// ── Refine panel (inline) ────────────────────────────────────────────────

function RefinePanel({
  refine,
  onDone,
}: {
  refine: ReturnType<typeof useRefinePlan>
  onDone: () => void
}) {
  const [instructions, setInstructions] = useState('')

  async function handleSubmit() {
    const trimmed = instructions.trim()
    if (!trimmed) return
    try {
      await refine.mutateAsync(trimmed)
      toast.success('Plan refined')
      setInstructions('')
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refinement failed')
    }
  }

  return (
    <div className="shrink-0 border-b bg-muted/30 p-3">
      <div className="mx-auto max-w-3xl space-y-2">
        <p className="text-[11px] text-muted-foreground">
          Describe the plan you want. The Planning Agent will produce a
          new TaskPlan based on the mission brief + your instructions.
          task_ids are preserved for unchanged tasks so approvals and run
          history survive.
        </p>
        <Textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. Split the code-quality audit into two tasks: one for style, one for security. Add a final task that summarises findings."
          rows={3}
          className="resize-none text-[12px]"
          disabled={refine.isPending}
        />
        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-[11px]"
            onClick={onDone}
            disabled={refine.isPending}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="h-6 gap-1 px-3 text-[11px]"
            onClick={handleSubmit}
            disabled={refine.isPending || !instructions.trim()}
          >
            {refine.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            {refine.isPending ? 'Refining…' : 'Refine plan'}
          </Button>
        </div>
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
  def: ColumnDef
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

// ── Add task inline form ─────────────────────────────────────────────────

function AddTaskForm({
  missionId,
  onDone,
}: {
  missionId: string
  onDone: () => void
}) {
  const [description, setDescription] = useState('')
  const [agentInput, setAgentInput] = useState('')
  const addTask = useAddPlanTask(missionId)
  const { data: team } = useTeam(missionId)

  const agentNames = (team ?? [])
    .filter((m) => m.enabled && m.agent?.agent_name)
    .map((m) => m.agent!.agent_name)

  async function handleSubmit() {
    const desc = description.trim()
    const agent = agentInput.trim()
    if (!desc || !agent) return
    try {
      await addTask.mutateAsync({ description: desc, agent })
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add task')
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { onDone(); return }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  return (
    <div className="mt-1.5 rounded-lg border bg-card p-2.5 space-y-2 shadow-sm">
      <Textarea
        autoFocus
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Task description…"
        rows={2}
        className="resize-none text-[12px]"
        disabled={addTask.isPending}
      />
      {agentNames.length > 0 ? (
        <select
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          disabled={addTask.isPending}
          className="w-full rounded border bg-transparent px-2 py-1 text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="">Select agent…</option>
          {agentNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      ) : (
        <input
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Agent name (e.g. code.agent)"
          className="w-full rounded border bg-transparent px-2 py-1 text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          disabled={addTask.isPending}
        />
      )}
      <div className="flex items-center justify-end gap-1.5">
        <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={onDone} disabled={addTask.isPending}>
          Cancel
        </Button>
        <Button
          size="sm"
          className="h-6 px-3 text-[11px]"
          onClick={handleSubmit}
          disabled={addTask.isPending || !description.trim() || !agentInput.trim()}
        >
          {addTask.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Add task'}
        </Button>
      </div>
    </div>
  )
}

// ── Task card ────────────────────────────────────────────────────────────

function TaskCard({
  row,
  missionId,
  cardRef,
  dragInnerRef,
  draggableProps,
  dragHandleProps,
  isDragging,
}: {
  row: AnnotatedTask
  missionId: string
  cardRef: RefCallback<HTMLDivElement>
  dragInnerRef?: (el: HTMLDivElement | null) => void
  draggableProps?: React.HTMLAttributes<HTMLDivElement>
  dragHandleProps?: React.HTMLAttributes<HTMLSpanElement> | null
  isDragging?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const approve = useApproveTask(missionId)
  const reject = useRejectTask(missionId)
  const retry = useRetryTask(missionId)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  const { body, state, effectiveStatus, blocked, blockingDeps } = row
  const agentShort = body.agent.endsWith('.agent')
    ? body.agent.slice(0, -6)
    : body.agent

  // Live tool call for this task's agent, only when running. Zustand
  // selector returns a single string so re-renders stay scoped to the
  // card whose agent's tool actually changed.
  const currentTool = useWorkspaceStore((s) =>
    effectiveStatus === 'running' ? s.agentStatuses[body.agent]?.currentTool ?? null : null,
  )

  // Plan 42 §4.4: live countdown for the ai_assisted auto-approval veto
  // window. Only meaningful when the task is currently approved AND was
  // auto-approved by the Director (has a veto_expires_at timestamp).
  const veto = useVetoCountdown(state?.veto_expires_at)
  const inVetoWindow =
    effectiveStatus === 'approved' && veto !== null && !veto.expired

  async function handleApprove() {
    try {
      const result = await approve.mutateAsync(body.task_id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(
          `Approved ${result.transitioned_task_ids.length} tasks (dependencies included)`,
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Approve failed')
    }
  }

  async function handleReject() {
    try {
      const result = await reject.mutateAsync(body.task_id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(
          `Cancelled ${result.transitioned_task_ids.length} tasks (dependents included)`,
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Reject failed')
    }
  }

  async function handleRetry() {
    try {
      await retry.mutateAsync(body.task_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Retry failed')
    }
  }

  const borderClass = getBorderClass(effectiveStatus)
  const dimmed =
    blocked ||
    effectiveStatus === 'cancelled' ||
    effectiveStatus === 'skipped'

  return (
    <div
      ref={(el) => { cardRef(el); dragInnerRef?.(el) }}
      {...draggableProps}
      {...(dragHandleProps ?? {})}
      className={cn(
        'relative rounded-md border bg-card shadow-sm p-2.5 text-xs transition-colors',
        borderClass,
        dimmed && 'opacity-60',
        isDragging && 'shadow-xl ring-1 ring-primary/30 rotate-[0.5deg] opacity-95',
        dragHandleProps && !isDragging && 'cursor-grab active:cursor-grabbing',
        dragHandleProps && 'pl-5',
      )}
    >
      {/* Visual drag grip hint — pointer-events-none so it doesn't intercept clicks */}
      {dragHandleProps && (
        <span
          className="absolute left-0 top-0 flex h-full w-4 items-center justify-center text-muted-foreground/30 pointer-events-none"
          aria-hidden
        >
          <GripVertical className="h-3 w-3" />
        </span>
      )}

      {/* Header: domain-colored agent badge + blocked pill + veto + status + menu */}
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className={cn(
            'inline-flex max-w-[120px] items-center truncate rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider',
            getAgentBadgeClass(effectiveStatus, body.agent),
          )}
          title={body.agent}
        >
          {agentShort}
        </span>
        {blocked && (
          <span
            className="flex items-center gap-0.5 text-[9px] text-muted-foreground/60"
            title={`Blocked by: ${blockingDeps.join(', ')}`}
          >
            <Lock className="h-2.5 w-2.5" />
            blocked
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {inVetoWindow && veto && (
            <span
              className="flex items-center gap-0.5 rounded bg-amber-500/10 px-1 py-0.5 text-[9px] text-amber-400"
              title="Auto-approved by the Director — click X to veto before expiry"
            >
              <Clock className="h-2.5 w-2.5" />
              {veto.remainingSec}s
            </span>
          )}
          <StatusIcon status={effectiveStatus} />
          {/* ⋮ card menu */}
          <div ref={menuRef} className="relative">
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v) }}
              className="rounded p-0.5 text-muted-foreground/25 hover:text-muted-foreground/70 hover:bg-accent"
              title="More actions"
            >
              <MoreVertical className="h-3 w-3" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-5 z-50 min-w-[130px] rounded-md border bg-popover shadow-md py-0.5 text-[11px]">
                {(effectiveStatus === 'proposed' || effectiveStatus === 'approved' || effectiveStatus === 'queued') && (
                  <button
                    onClick={() => { setMenuOpen(false); handleReject() }}
                    disabled={reject.isPending}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-destructive hover:bg-accent disabled:opacity-40"
                  >
                    <X className="h-3 w-3" />
                    {effectiveStatus === 'proposed' ? 'Reject' : 'Cancel'}
                  </button>
                )}
                {effectiveStatus === 'failed' && (
                  <button
                    onClick={() => { setMenuOpen(false); handleRetry() }}
                    disabled={retry.isPending}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-accent disabled:opacity-40"
                  >
                    <RotateCcw className="h-3 w-3" />
                    Retry
                  </button>
                )}
                <div className="mx-2 my-0.5 border-t border-border/50" />
                <p className="px-3 py-1 font-mono text-[10px] text-muted-foreground/50 truncate max-w-[160px]">
                  {body.task_id}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="text-[12px] leading-snug">
        {body.description || body.task_id}
      </p>

      {/* Live tool indicator on running cards */}
      {currentTool && (
        <div className="mt-1 flex items-center gap-1 text-[10px] text-amber-400/80">
          <Wrench className="h-2.5 w-2.5 shrink-0" />
          <span className="truncate">{currentTool}</span>
        </div>
      )}

      {/* Meta line: cost/duration (terminal only) + retries + dep count.
          Cost/duration are Plan 46 Phase 2 #2: denormalised from
          task_executions at run completion. Hidden for pre-run and
          running states — a proposed/queued/running task legitimately
          shows "no cost yet" which we render as no pill rather than
          "$0.0000 · 0.0s". */}
      {(() => {
        const terminal =
          effectiveStatus === 'completed' || effectiveStatus === 'failed'
        const showMetrics =
          !!state &&
          terminal &&
          (state.cost_usd > 0 || state.duration_seconds > 0)
        const hasMeta =
          showMetrics ||
          !!state?.retry_count ||
          body.dependencies.length > 0
        if (!hasMeta) return null
        return (
          <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground/60">
            {showMetrics && state && (
              <span className="tabular-nums" title="Cost · duration">
                ${state.cost_usd.toFixed(4)} · {state.duration_seconds.toFixed(1)}s
              </span>
            )}
            {state && state.retry_count > 0 && (
              <span className="text-amber-400/70">
                {state.retry_count} {state.retry_count === 1 ? 'retry' : 'retries'}
              </span>
            )}
            {body.dependencies.length > 0 && (
              <span title={`Depends on: ${body.dependencies.join(', ')}`}>
                {body.dependencies.length} dep
                {body.dependencies.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
        )
      })()}

      {/* Result / failure preview */}
      {state?.result_summary && effectiveStatus === 'completed' && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 flex items-center gap-0.5 text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80"
          >
            {expanded ? (
              <ChevronDown className="h-2.5 w-2.5" />
            ) : (
              <ChevronRight className="h-2.5 w-2.5" />
            )}
            {expanded ? 'hide result' : 'show result'}
          </button>
          {expanded && (
            <div className="mt-1.5 border-t border-border/50 pt-1.5">
              <MarkdownRenderer
                content={state.result_summary}
                className="text-[11px]"
              />
            </div>
          )}
        </>
      )}

      {state?.failure_reason && effectiveStatus === 'failed' && (
        <p className="mt-1.5 line-clamp-2 text-[10px] text-destructive/70">
          {state.failure_reason}
        </p>
      )}

      {/* Actions footer */}
      <div className="mt-1.5 flex items-center justify-end gap-1">
        {effectiveStatus === 'proposed' && (
          <>
            <IconButton
              icon={<Check className="h-3 w-3" />}
              title="Approve (with transitive dependencies)"
              onClick={handleApprove}
              disabled={approve.isPending}
              tone="emerald"
            />
            <IconButton
              icon={<X className="h-3 w-3" />}
              title="Reject (with transitive dependents)"
              onClick={handleReject}
              disabled={reject.isPending}
              tone="destructive"
            />
          </>
        )}
        {(effectiveStatus === 'approved' || effectiveStatus === 'queued') && (
          <IconButton
            icon={<X className="h-3 w-3" />}
            title={
              inVetoWindow
                ? `Veto this auto-approval (${veto?.remainingSec ?? 0}s remaining)`
                : 'Unapprove (reject)'
            }
            onClick={handleReject}
            disabled={reject.isPending}
            tone={inVetoWindow ? 'amber' : 'muted'}
          />
        )}
        {effectiveStatus === 'failed' && (
          <IconButton
            icon={<RotateCcw className="h-3 w-3" />}
            title="Retry this task"
            onClick={handleRetry}
            disabled={retry.isPending}
            tone="amber"
          />
        )}
      </div>

      {/* Indeterminate progress bar for running cards */}
      {effectiveStatus === 'running' && (
        <div className="mt-2 h-[2px] w-full overflow-hidden rounded-full bg-amber-500/15">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-amber-400/60" />
        </div>
      )}
    </div>
  )
}

// ── Shimmer placeholder (refining) ───────────────────────────────────────

function ShimmerCard() {
  return (
    <div className="rounded-md border border-primary/30 bg-card shadow-sm p-2.5">
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 animate-pulse text-primary/60" />
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Refining plan…
        </span>
      </div>
      <div className="mt-2 space-y-1">
        <div className="h-2 w-4/5 animate-pulse rounded bg-muted" />
        <div className="h-2 w-3/5 animate-pulse rounded bg-muted" />
      </div>
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

// ── Presentation helpers ─────────────────────────────────────────────────

function StatusIcon({ status }: { status: PlanTaskStatus }) {
  switch (status) {
    case 'proposed':
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/50" />
    case 'approved':
      return <Circle className="h-3 w-3 shrink-0 fill-primary/40 text-primary" />
    case 'queued':
      return <Circle className="h-3 w-3 shrink-0 fill-amber-500/30 text-amber-500" />
    case 'running':
      return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-amber-400" />
    case 'completed':
      return <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
    case 'failed':
      return <XCircle className="h-3 w-3 shrink-0 text-destructive" />
    case 'skipped':
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/30" />
    case 'cancelled':
      return <X className="h-3 w-3 shrink-0 text-muted-foreground/40" />
    default:
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/30" />
  }
}

function getBorderClass(status: PlanTaskStatus): string {
  switch (status) {
    case 'running':
      return 'border-amber-500/40'
    case 'completed':
      return 'border-emerald-500/25'
    case 'failed':
      return 'border-destructive/40'
    case 'cancelled':
    case 'skipped':
      return 'border-border/30'
    case 'approved':
    case 'queued':
      return 'border-primary/30'
    default:
      return 'border-border'
  }
}

const AGENT_DOMAIN_COLORS: Record<string, string> = {
  code: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  software: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  dev: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  engineer: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  research: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  analyst: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  analysis: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  security: 'bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/30',
  audit: 'bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/30',
  writer: 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30',
  content: 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30',
  data: 'bg-cyan-500/10 text-cyan-400 ring-1 ring-inset ring-cyan-500/30',
  mission: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
  director: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
  planning: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
}

function getAgentDomainClass(agentName: string): string {
  const domain = agentName.split('.')[0].toLowerCase()
  return AGENT_DOMAIN_COLORS[domain] ?? 'bg-muted text-muted-foreground ring-1 ring-inset ring-border/50'
}

function getAgentBadgeClass(status: PlanTaskStatus, agentName: string): string {
  switch (status) {
    case 'running':
      return 'bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30'
    case 'completed':
      return 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30'
    case 'failed':
      return 'bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30'
    default:
      // For proposed/approved/queued/cancelled/skipped: use domain color
      return getAgentDomainClass(agentName)
  }
}

function IconButton({
  icon,
  title,
  onClick,
  disabled,
  tone,
}: {
  icon: React.ReactNode
  title: string
  onClick: () => void
  disabled?: boolean
  tone: 'emerald' | 'destructive' | 'amber' | 'muted'
}) {
  const toneClass =
    tone === 'emerald'
      ? 'text-emerald-400 hover:bg-emerald-500/10'
      : tone === 'destructive'
        ? 'text-destructive hover:bg-destructive/10'
        : tone === 'amber'
          ? 'text-amber-400 hover:bg-amber-500/10'
          : 'text-muted-foreground hover:bg-accent'

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        'rounded-md p-1 transition-colors disabled:opacity-40',
        toneClass,
      )}
    >
      {icon}
    </button>
  )
}

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

function computeEdges(joined: JoinedTask[]): Edge[] {
  const byId = new Map(joined.map((j) => [j.body.task_id, j]))
  const edges: Edge[] = []
  for (const j of joined) {
    for (const depId of j.body.dependencies) {
      const blocker = byId.get(depId)
      if (!blocker) continue
      const bs = blocker.effectiveStatus
      let state: Edge['state'] = 'grey'
      if (bs === 'running') state = 'amber'
      else if (bs === 'completed' || bs === 'skipped') state = 'green'
      else if (bs === 'failed' || bs === 'cancelled') state = 'failed'
      edges.push({ from: depId, to: j.body.task_id, state })
    }
  }
  return edges
}

function bezierPath(from: Rect, to: Rect): string {
  const x1 = from.right
  const y1 = from.top + from.height / 2
  const x2 = to.left
  const y2 = to.top + to.height / 2
  // Control-point offset: minimum 60px, scale with horizontal distance so
  // curves don't look collapsed when cards are right next to each other.
  const dx = Math.max(60, Math.abs(x2 - x1) * 0.35)
  return `M ${x1},${y1} C ${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
}

function edgeColor(state: Edge['state']): string {
  switch (state) {
    case 'amber':
      return 'rgb(251 191 36 / 0.75)' // amber-400
    case 'green':
      return 'rgb(52 211 153 / 0.35)' // emerald-400, faded
    case 'failed':
      return 'rgb(239 68 68 / 0.45)' // red-500, muted
    default:
      return 'rgb(148 163 184 / 0.35)' // slate-400, muted
  }
}

// ── Veto-window countdown (Plan 42 §4.4) ─────────────────────────────────

interface VetoState {
  /** Whole seconds remaining until the window expires. 0 when expired. */
  remainingSec: number
  /** True once the timestamp has passed — veto is no longer available. */
  expired: boolean
}

/**
 * Live countdown for an ai_assisted auto-approval veto window.
 *
 * Returns null when `vetoExpiresAt` is null/undefined (no window — the
 * task is a manual approval, not a Director auto-approval). Otherwise
 * ticks every second until expiry, then stops and returns expired: true.
 *
 * One interval per active countdown, auto-cleared on unmount or when the
 * input timestamp changes.
 */
function useVetoCountdown(
  vetoExpiresAt: string | null | undefined,
): VetoState | null {
  const [now, setNow] = useState<number>(() => Date.now())

  useEffect(() => {
    if (!vetoExpiresAt) return
    const expiry = new Date(vetoExpiresAt).getTime()
    if (Date.now() >= expiry) return // already expired — no timer needed
    const interval = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [vetoExpiresAt])

  if (!vetoExpiresAt) return null
  const expiry = new Date(vetoExpiresAt).getTime()
  const remainingMs = expiry - now
  return {
    remainingSec: Math.max(0, Math.ceil(remainingMs / 1000)),
    expired: remainingMs <= 0,
  }
}
