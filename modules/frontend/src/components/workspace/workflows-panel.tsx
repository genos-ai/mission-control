/**
 * WorkflowsPanel — Workflows feed mode (placeholder for Plan 45).
 *
 * Lists mission-scoped workflows and system templates. The visual
 * editor (Plan 45 §Phase 4) is not yet built — for now, clicking a
 * workflow shows a "Coming in Plan 45" placeholder and the [Use
 * template] button works (it clones a template into the mission via
 * the existing useImportTemplate hook).
 *
 * Shipping this as a thin feed mode now means:
 *   - Users see workflows in the expected place (consistent with the
 *     Plan / Runs / Context feed modes)
 *   - The mission-scoped vs template distinction is visible from day 1
 *   - Template cloning — the one operation that works today — gets
 *     a proper UI
 *   - Plan 45's Phase 4 (editor) has a natural slot to drill into
 *
 * The existing legacy route /missions/:id/workflows still exists for
 * anyone with a deep link, but the primary access point is now this
 * feed mode.
 */

import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import {
  GitBranch,
  Play,
  Pencil,
  Copy,
  Plus,
  CheckCircle2,
  Circle,
  Loader2,
  Trash2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import {
  useMissionWorkflows,
  useWorkflowTemplates,
  useImportTemplate,
  useCreateWorkflow,
  useRunWorkflow,
  useDeleteWorkflow,
} from '@/hooks/use-workflows'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import type { MissionWorkflow, WorkflowListItem } from '@/types'

// ── Root ────────────────────────────────────────────────────────────────

export function WorkflowsPanel({ missionId }: { missionId: string }) {
  const navigate = useNavigate()
  const { data: missionWorkflows, isLoading: loadingMission } = useMissionWorkflows(missionId)
  const { data: templates, isLoading: loadingTemplates } = useWorkflowTemplates()
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
    <div className="flex h-full flex-col">
      {/* Status bar */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b px-4">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Workflows
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-5 gap-1 px-2 text-[11px]"
          onClick={handleCreate}
          disabled={createWorkflow.isPending}
        >
          {createWorkflow.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
          New workflow
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-4">
          <MissionWorkflowsSection
            missionId={missionId}
            workflows={missionWorkflows}
            loading={loadingMission}
          />
          <TemplatesSection
            missionId={missionId}
            templates={templates}
            loading={loadingTemplates}
          />
        </div>
      </div>
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
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 px-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Mission Workflows
        </span>
        {workflows && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">
            {workflows.length}
          </Badge>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <Spinner className="h-4 w-4" />
        </div>
      ) : !workflows || workflows.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 bg-muted/20 px-4 py-6 text-center">
          <GitBranch className="mx-auto mb-2 h-5 w-5 text-muted-foreground/40" />
          <p className="text-xs text-muted-foreground/70">
            No workflows yet.
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground/50">
            Clone a template below, or ask the Workflow Architect in chat:
            <br />
            <span className="font-mono">"Design a workflow that…"</span>
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {workflows.map((w) => (
            <MissionWorkflowRow
              key={w.id}
              workflow={w}
              missionId={missionId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function MissionWorkflowRow({
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

  async function handleRun() {
    try {
      const result = await runMutation.mutateAsync(workflow.name)
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

  return (
    <div
      className="group flex items-center gap-3 rounded-md border bg-card px-3 py-2.5"
      onMouseLeave={() => setConfirmDelete(false)}
    >
      {workflow.enabled ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
      ) : (
        <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-[13px] font-medium">{workflow.name}</p>
          <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">
            v{workflow.version}
          </Badge>
          <Badge variant="outline" className="h-4 px-1.5 text-[9px]">
            {workflow.step_count} step{workflow.step_count === 1 ? '' : 's'}
          </Badge>
          {workflow.locked_at && (
            <Badge variant="outline" className="h-4 px-1.5 text-[9px]">
              locked
            </Badge>
          )}
        </div>
        {workflow.description && (
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground/70">
            {workflow.description}
          </p>
        )}
        <p className="mt-0.5 text-[10px] text-muted-foreground/50">
          designed by {workflow.designed_by || 'unknown'}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <IconButton
          icon={
            runMutation.isPending
              ? <Loader2 className="h-3 w-3 animate-spin" />
              : <Play className="h-3 w-3" />
          }
          title="Run workflow"
          onClick={handleRun}
          disabled={runMutation.isPending || !workflow.enabled}
          tone="emerald"
        />
        <IconButton
          icon={<Pencil className="h-3 w-3" />}
          title="Edit workflow in visual editor"
          onClick={() => {
            navigate(ROUTES.MISSION_WORKFLOW_EDIT(missionId, workflow.id))
          }}
          tone="muted"
        />
        {isAdmin && (
          <IconButton
            icon={
              deleteMutation.isPending
                ? <Loader2 className="h-3 w-3 animate-spin" />
                : <Trash2 className="h-3 w-3" />
            }
            title={confirmDelete ? 'Click again to confirm delete' : 'Delete workflow'}
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            tone={confirmDelete ? 'red' : 'muted'}
          />
        )}
      </div>
    </div>
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
      <div className="mb-2 flex items-center gap-2 px-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Templates (clone to use)
        </span>
        {templates && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">
            {templates.length}
          </Badge>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <Spinner className="h-4 w-4" />
        </div>
      ) : !templates || templates.length === 0 ? (
        <p className="px-4 py-4 text-[11px] text-muted-foreground/50">
          No system templates available.
        </p>
      ) : (
        <div className="space-y-1.5">
          {templates.map((t) => (
            <TemplateRow
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

function TemplateRow({
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
    <div className="flex items-center gap-3 rounded-md border border-dashed bg-muted/10 px-3 py-2">
      <Copy className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-[13px] font-medium">
            {template.workflow_name}
          </p>
          <Badge variant="outline" className="h-4 px-1.5 text-[9px]">
            {template.step_count} step{template.step_count === 1 ? '' : 's'}
          </Badge>
        </div>
        {template.description && (
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground/60">
            {template.description}
          </p>
        )}
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 gap-1 px-2 text-[11px]"
        onClick={handleClone}
        disabled={importMutation.isPending}
      >
        {importMutation.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
        Use template
      </Button>
    </div>
  )
}

// ── Small helpers ──────────────────────────────────────────────────────

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
  tone: 'emerald' | 'muted' | 'red'
}) {
  const toneClass =
    tone === 'emerald'
      ? 'text-emerald-400 hover:bg-emerald-500/10'
      : tone === 'red'
        ? 'text-red-500 bg-red-100/10 hover:bg-red-500/20'
        : 'text-muted-foreground hover:bg-accent'
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-md p-1 transition-colors disabled:opacity-40 ${toneClass}`}
    >
      {icon}
    </button>
  )
}
