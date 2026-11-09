/**
 * WorkflowsPanel — the mission's Workflows tab.
 *
 * Mission workflows and mission schedules, plus system templates that can be cloned
 * into the mission. Each workflow is a card; the visual editor opens from its
 * Edit action. The route /missions/:id/workflows is the primary access point.
 */

import { useNavigate } from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import {
  Archive,
  ChevronRight,
  GitBranch,
  Play,
  Pause,
  Pencil,
  Copy,
  Plus,
  Clock,
  Loader2,
  Trash2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import {
  useMissionWorkflows,
  useWorkflowTemplates,
  useImportTemplate,
  useCreateWorkflow,
  useRunWorkflow,
  useDeleteWorkflow,
} from '@/hooks/use-workflows'
import {
  useArchiveMissionSchedule,
  useMissionSchedule,
  useMissionSchedules,
  usePauseMissionSchedule,
  useResumeMissionSchedule,
} from '@/hooks/use-mission-schedules'
import { ScheduleModal } from '@/components/workflow/schedule-modal'
import { cn } from '@/lib/cn'
import { describeCronExpression } from '@/lib/cron'
import { formatUtc } from '@/lib/format-date'
import { statusLabel } from '@/lib/format'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import type {
  MissionScheduleResponse,
  MissionScheduleStatus,
  MissionWorkflow,
  WorkflowListItem,
} from '@/types'

const CARD_GRID = 'grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-gutter'
// Row actions stay visible: they are the card's main controls, and touch has no hover.
const ACTIONS = 'flex shrink-0 items-center gap-0.5'

const stepsLabel = (n: number) => `${n} step${n === 1 ? '' : 's'}`

function SectionHeader({
  title,
  count,
  action,
}: {
  title: string
  count: number | undefined
  action?: ReactNode
}) {
  return (
    <div className="mb-2 flex items-center gap-2 px-1">
      <h2 className="text-base font-medium">{title}</h2>
      {count !== undefined && <span className="text-xs text-subtle">{count}</span>}
      {action && <div className="ml-auto">{action}</div>}
    </div>
  )
}

function LoadingPanel() {
  return (
    <Panel className="flex justify-center py-6">
      <Spinner />
    </Panel>
  )
}

function NoticePanel({ children }: { children: string }) {
  return <Panel className="px-4 py-4 text-sm text-subtle">{children}</Panel>
}

// ── Root ────────────────────────────────────────────────────────────────

export function WorkflowsPanel({ missionId }: { missionId: string }) {
  const navigate = useNavigate()
  const { data: missionWorkflows, isLoading: loadingMission } = useMissionWorkflows(missionId)
  const { data: templates, isLoading: loadingTemplates } = useWorkflowTemplates()
  const { data: schedules, isLoading: loadingSchedules } = useMissionSchedules(missionId, false)
  const createWorkflow = useCreateWorkflow(missionId)

  const handleCreate = () => {
    const name = window.prompt('Workflow name (lowercase, hyphens, underscores):')
    if (!name) return
    const sanitized = name.trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '')
    if (!sanitized) return
    createWorkflow.mutate({ name: sanitized }, {
      onSuccess: (data) => {
        toast.success(`Created workflow: ${data.name}`)
        navigate(ROUTES.MISSION_WORKFLOW_EDIT(missionId, data.id))
      },
      onError: () => toast.error('Failed to create workflow'),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-medium">Workflows</h1>
        {missionWorkflows && <span className="text-xs text-subtle">{missionWorkflows.length}</span>}
        <Button className="ml-auto" onClick={handleCreate} disabled={createWorkflow.isPending}>
          {createWorkflow.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          New workflow
        </Button>
      </div>

      <MissionWorkflowsSection
        missionId={missionId}
        workflows={missionWorkflows}
        loading={loadingMission}
      />
      <SchedulesSection
        missionId={missionId}
        schedules={schedules}
        workflows={missionWorkflows}
        loading={loadingSchedules}
      />
      <TemplatesSection
        missionId={missionId}
        templates={templates}
        loading={loadingTemplates}
      />
    </div>
  )
}

// ── Mission workflows section ───────────────────────────────────────────

function MissionWorkflowsSection({
  missionId,
  workflows,
  loading,
}: {
  missionId: string
  workflows: MissionWorkflow[] | undefined
  loading: boolean
}) {
  if (loading) return <LoadingPanel />
  if (!workflows || workflows.length === 0) {
    return (
      <Panel>
        <EmptyState
          icon={<GitBranch className="h-4 w-4" />}
          title="No workflows yet"
          description={'Clone a template below, or ask the Workflow Architect in chat: "Design a workflow that…"'}
        />
      </Panel>
    )
  }
  return (
    <div className={CARD_GRID}>
      {workflows.map((w) => (
        <MissionWorkflowCard key={w.id} workflow={w} missionId={missionId} />
      ))}
    </div>
  )
}

function MissionWorkflowCard({
  workflow,
  missionId,
}: {
  workflow: MissionWorkflow
  missionId: string
}) {
  const navigate = useNavigate()
  const runMutation = useRunWorkflow(missionId)
  const deleteMutation = useDeleteWorkflow(missionId)
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showSchedule, setShowSchedule] = useState(false)

  async function handleRun() {
    try {
      const result = await runMutation.mutateAsync({ workflowName: workflow.name })
      toast.success(
        `Workflow started — ${result.workflow_name} (${result.status})`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to run workflow')
    }
  }

  async function handleDelete() {
    if (!confirmDelete) { setConfirmDelete(true); return }
    try {
      await deleteMutation.mutateAsync(workflow.id)
      toast.success(`Deleted workflow "${workflow.name}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
    setConfirmDelete(false)
  }

  const runTitle = 'Run workflow'
  const editTitle = 'Edit workflow in visual editor'
  const scheduleTitle = 'Schedule this workflow'
  const deleteTitle = confirmDelete ? 'Click again to confirm delete' : 'Delete workflow'

  return (
    <>
      <Panel
        className="flex flex-col gap-3 p-4"
        onMouseLeave={() => setConfirmDelete(false)}
      >
        <div className="flex items-start gap-3">
          <IconTile icon={GitBranch} size="lg" shape="square" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-md font-medium">{workflow.name}</p>
            <p className="truncate text-xs text-subtle">
              {workflow.trigger_type} · {stepsLabel(workflow.step_count)}
            </p>
          </div>
        </div>

        {workflow.description && (
          <p className="line-clamp-2 text-xs text-text-3">{workflow.description}</p>
        )}

        <p className="mt-auto truncate text-2xs text-subtle" title={`designed by ${workflow.designed_by || 'unknown'}`}>
          designed by {workflow.designed_by || 'unknown'}
        </p>
        <div className="flex items-center gap-1.5">
          <StatusPill tone={workflow.enabled ? 'success' : 'neutral'}>
            {workflow.enabled ? 'enabled' : 'disabled'}
          </StatusPill>
          <Badge>v{workflow.version}</Badge>
          {workflow.locked_at && <StatusPill tone="neutral">locked</StatusPill>}
          <div className={cn(ACTIONS, 'ml-auto')}>
            <Button
              variant="ghost"
              size="icon-sm"
              title={runTitle}
              aria-label={runTitle}
              onClick={handleRun}
              disabled={runMutation.isPending || !workflow.enabled}
            >
              {runMutation.isPending ? <Spinner className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              title={editTitle}
              aria-label={editTitle}
              onClick={() => {
                navigate(ROUTES.MISSION_WORKFLOW_EDIT(missionId, workflow.id))
              }}
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              title={scheduleTitle}
              aria-label={scheduleTitle}
              onClick={() => setShowSchedule(true)}
            >
              <Clock className="h-3 w-3" />
            </Button>
            {isAdmin && (
              <Button
                variant={confirmDelete ? 'destructive' : 'ghost'}
                size="icon-sm"
                title={deleteTitle}
                aria-label={deleteTitle}
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? <Spinner className="h-3 w-3" /> : <Trash2 className="h-3 w-3" />}
              </Button>
            )}
          </div>
        </div>
      </Panel>
      {showSchedule && (
        <ScheduleModal
          missionId={missionId}
          workflowDefinitionId={workflow.id}
          onClose={() => setShowSchedule(false)}
        />
      )}
    </>
  )
}

// ── Schedules section ───────────────────────────────────────────────────

const SCHEDULE_STATUS_TONE: Record<MissionScheduleStatus, 'success' | 'warning' | 'neutral'> = {
  active: 'success',
  paused: 'warning',
  completed: 'neutral',
  archived: 'neutral',
}

function SchedulesSection({
  missionId,
  schedules,
  workflows,
  loading,
}: {
  missionId: string
  schedules: MissionScheduleResponse[] | undefined
  workflows: MissionWorkflow[] | undefined
  loading: boolean
}) {
  const nameById = new Map((workflows ?? []).map((w) => [w.id, w.name]))
  const [showCreate, setShowCreate] = useState(false)

  return (
    <div>
      <SectionHeader
        title="Schedules"
        count={schedules?.length}
        action={
          <Button size="sm" variant="secondary" onClick={() => setShowCreate(true)}>
            <Plus className="h-3 w-3" />
            New schedule
          </Button>
        }
      />

      {loading ? (
        <LoadingPanel />
      ) : !schedules || schedules.length === 0 ? (
        <NoticePanel>No schedules. Create one, or use the clock icon on a workflow.</NoticePanel>
      ) : (
        <div className="flex flex-col gap-gutter">
          {schedules.map((s) => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              missionId={missionId}
              workflowName={
                s.workflow_definition_id
                  ? nameById.get(s.workflow_definition_id) ?? s.workflow_definition_id
                  : undefined
              }
            />
          ))}
        </div>
      )}
      {showCreate && (
        <ScheduleModal missionId={missionId} onClose={() => setShowCreate(false)} />
      )}
    </div>
  )
}

function ScheduleRow({
  schedule,
  missionId,
  workflowName,
}: {
  schedule: MissionScheduleResponse
  missionId: string
  workflowName: string | undefined
}) {
  const pauseMutation = usePauseMissionSchedule(missionId)
  const resumeMutation = useResumeMissionSchedule(missionId)
  const archiveMutation = useArchiveMissionSchedule(missionId)
  const [expanded, setExpanded] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const busy = pauseMutation.isPending || resumeMutation.isPending || archiveMutation.isPending

  function run(mutation: typeof pauseMutation, done: string) {
    mutation.mutate(schedule.id, {
      onSuccess: () => toast.success(done),
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Schedule update failed'),
    })
  }

  function handleArchive() {
    if (!confirmArchive) { setConfirmArchive(true); return }
    run(archiveMutation, 'Schedule archived')
    setConfirmArchive(false)
  }

  const target = schedule.kind === 'objective' ? schedule.objective_template : `workflow ${workflowName}`
  const editTitle = 'Edit schedule'
  const archiveTitle = confirmArchive ? 'Click again to confirm archive' : 'Archive schedule'
  const runs = schedule.max_runs
    ? `${schedule.executed_run_count}/${schedule.max_runs}`
    : `${schedule.executed_run_count}`

  return (
    <>
      <Panel className="group px-4 py-3" onMouseLeave={() => setConfirmArchive(false)}>
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-expanded={expanded}
            aria-label={expanded ? 'Hide next fire time' : 'Show next fire time'}
            onClick={() => setExpanded((e) => !e)}
          >
            <ChevronRight
              className={cn('h-3 w-3 transition-transform duration-150', expanded && 'rotate-90')}
            />
          </Button>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-md font-medium">{schedule.name}</p>
              <StatusPill tone={SCHEDULE_STATUS_TONE[schedule.status]}>
                {statusLabel(schedule.status)}
              </StatusPill>
              {schedule.temporal_sync_state !== 'synced' && (
                <span title={schedule.temporal_sync_error ?? undefined}>
                  <StatusPill tone={schedule.temporal_sync_state === 'failed' ? 'danger' : 'warning'}>
                    sync {schedule.temporal_sync_state}
                  </StatusPill>
                </span>
              )}
              <Badge>{describeCronExpression(schedule.cron_expression)}</Badge>
            </div>
            {target && <p className="mt-0.5 truncate text-xs text-text-3">{target}</p>}
            <p className="mt-0.5 text-2xs text-subtle">
              runs {runs} · last {formatUtc(schedule.last_claimed_scheduled_for)}
              {' · '}{schedule.time_zone_name}
              {' · '}<span className="font-mono">{schedule.cron_expression}</span>
            </p>
          </div>

          <div className={ACTIONS}>
            {schedule.status === 'active' && (
              <Button
                variant="ghost"
                size="icon-sm"
                title="Pause schedule"
                aria-label="Pause schedule"
                onClick={() => run(pauseMutation, 'Schedule paused')}
                disabled={busy}
              >
                <Pause className="h-3 w-3" />
              </Button>
            )}
            {schedule.status === 'paused' && (
              <Button
                variant="ghost"
                size="icon-sm"
                title="Resume schedule"
                aria-label="Resume schedule"
                onClick={() => run(resumeMutation, 'Schedule resumed')}
                disabled={busy}
              >
                <Play className="h-3 w-3" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              title={editTitle}
              aria-label={editTitle}
              onClick={() => setShowEdit(true)}
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              variant={confirmArchive ? 'destructive' : 'ghost'}
              size="icon-sm"
              title={archiveTitle}
              aria-label={archiveTitle}
              onClick={handleArchive}
              disabled={busy}
            >
              {archiveMutation.isPending ? <Spinner className="h-3 w-3" /> : <Archive className="h-3 w-3" />}
            </Button>
          </div>
        </div>
        {expanded && <NextFire missionId={missionId} scheduleId={schedule.id} />}
      </Panel>
      {showEdit && (
        <ScheduleModal
          missionId={missionId}
          schedule={schedule}
          onClose={() => setShowEdit(false)}
        />
      )}
    </>
  )
}

/** The next fire time, read from Temporal through the single-schedule query. */
function NextFire({ missionId, scheduleId }: { missionId: string; scheduleId: string }) {
  const { data, isLoading } = useMissionSchedule(missionId, scheduleId)
  return (
    <p className="mt-2 pl-9 text-xs text-muted-foreground">
      {isLoading ? (
        <Spinner className="h-3 w-3" />
      ) : (
        <>next fire {formatUtc(data?.next_fire_times[0] ?? null)}</>
      )}
    </p>
  )
}

// ── Templates section ──────────────────────────────────────────────────

function TemplatesSection({
  missionId,
  templates,
  loading,
}: {
  missionId: string
  templates: WorkflowListItem[] | undefined
  loading: boolean
}) {
  return (
    <div>
      <SectionHeader title="Templates (clone to use)" count={templates?.length} />

      {loading ? (
        <LoadingPanel />
      ) : !templates || templates.length === 0 ? (
        <NoticePanel>No system templates available.</NoticePanel>
      ) : (
        <div className={CARD_GRID}>
          {templates.map((t) => (
            <TemplateCard
              key={t.workflow_name}
              template={t}
              missionId={missionId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function TemplateCard({
  template,
  missionId,
}: {
  template: WorkflowListItem
  missionId: string
}) {
  const importMutation = useImportTemplate(missionId)

  async function handleClone() {
    try {
      await importMutation.mutateAsync(template.workflow_name)
      toast.success(`Cloned ${template.workflow_name} into this mission`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Clone failed')
    }
  }

  return (
    <Panel className="flex flex-col gap-3 border-dashed p-4">
      <div className="flex items-start gap-3">
        <IconTile icon={Copy} size="lg" shape="square" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-md font-medium">{template.workflow_name}</p>
          <p className="truncate text-xs text-subtle">{stepsLabel(template.step_count)}</p>
        </div>
      </div>
      {template.description && (
        <p className="line-clamp-2 text-xs text-text-3">{template.description}</p>
      )}
      <Button
        size="sm"
        variant="secondary"
        className="mt-auto self-start"
        onClick={handleClone}
        disabled={importMutation.isPending}
      >
        {importMutation.isPending ? (
          <Spinner className="h-3 w-3" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
        Use template
      </Button>
    </Panel>
  )
}
