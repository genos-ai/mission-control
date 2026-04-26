/**
 * StepDetail — editable config panel for a selected workflow node.
 */

import { useEffect, useState } from 'react'
import { X, Bot, GitBranch, Bell, UserRound, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { WorkflowStep } from '@/types'

interface StepDetailProps {
  step: WorkflowStep
  onClose: () => void
  onUpdate: (updated: WorkflowStep) => void
  onDelete: () => void
}

export function StepDetail({ step, onClose, onUpdate, onDelete }: StepDetailProps) {
  const [draft, setDraft] = useState<WorkflowStep>(step)

  // Sync when a different step is selected
  useEffect(() => {
    setDraft(step)
  }, [step])

  const update = (partial: Partial<WorkflowStep>) => {
    const next = { ...draft, ...partial }
    setDraft(next)
    onUpdate(next)
  }

  const nodeType = draft.node_type ?? 'agent_step'
  const NodeIcon = nodeType === 'condition' ? GitBranch
    : nodeType === 'notification' ? Bell
    : nodeType === 'human_input' ? UserRound
    : Bot

  return (
    <div className="rounded-lg border bg-card p-4 shadow-md">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <NodeIcon className="h-4 w-4 text-muted-foreground" />
          <h4 className="font-semibold">{draft.id}</h4>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <Badge variant="outline" className="mb-3 text-[10px]">
        {nodeType.replace('_', ' ')}
      </Badge>

      <div className="space-y-3 text-sm">
        {/* Description — all node types */}
        <Field label="Description">
          <Textarea
            className="min-h-[40px] text-xs"
            value={draft.description ?? ''}
            placeholder="Optional description"
            onChange={(e) => update({ description: e.target.value || null })}
          />
        </Field>

        {/* ── Agent step fields ──────────────────────────── */}
        {nodeType === 'agent_step' && (
          <>
            <Field label="Capability">
              <Input
                className="h-8 text-xs"
                value={draft.capability ?? ''}
                placeholder="e.g. code.general"
                onChange={(e) => update({ capability: e.target.value || null })}
              />
            </Field>
            <Field label="Environment">
              <Select
                value={draft.environment}
                onChange={(v) => update({ environment: v })}
                options={['local', 'worktree', 'container', 'sandbox', 'auto']}
              />
            </Field>
            <Field label="Complexity">
              <Select
                value={draft.complexity_tier}
                onChange={(v) => update({ complexity_tier: v })}
                options={['simple', 'complex']}
              />
            </Field>
            <Field label="Termination">
              <Select
                value={draft.termination}
                onChange={(v) => update({ termination: v })}
                options={['completion', 'budget_exhausted', 'criteria_met', 'max_iterations']}
              />
            </Field>
            <Field label="Max Refinement Rounds">
              <Input
                className="h-8 text-xs"
                type="number"
                min={0}
                value={draft.max_refinement_rounds}
                onChange={(e) => update({ max_refinement_rounds: parseInt(e.target.value) || 0 })}
              />
            </Field>
            <Field label="Cost Ceiling ($)">
              <Input
                className="h-8 text-xs"
                type="number"
                min={0}
                step={0.01}
                value={draft.cost_ceiling_usd ?? ''}
                placeholder="No limit"
                onChange={(e) => update({ cost_ceiling_usd: e.target.value ? parseFloat(e.target.value) : null })}
              />
            </Field>
            <Field label="Timeout (seconds)">
              <Input
                className="h-8 text-xs"
                type="number"
                min={10}
                value={draft.timeout_seconds ?? ''}
                placeholder="No timeout"
                onChange={(e) => update({ timeout_seconds: e.target.value ? parseInt(e.target.value) : null })}
              />
            </Field>
          </>
        )}

        {/* ── Condition fields ───────────────────────────── */}
        {nodeType === 'condition' && draft.condition_config && (
          <>
            <Field label="Expression">
              <Textarea
                className="min-h-[50px] font-mono text-xs"
                value={draft.condition_config.expression}
                onChange={(e) =>
                  update({
                    condition_config: { ...draft.condition_config!, expression: e.target.value },
                  })
                }
              />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="True label">
                <Input
                  className="h-8 text-xs"
                  value={draft.condition_config.true_label}
                  onChange={(e) =>
                    update({
                      condition_config: { ...draft.condition_config!, true_label: e.target.value },
                    })
                  }
                />
              </Field>
              <Field label="False label">
                <Input
                  className="h-8 text-xs"
                  value={draft.condition_config.false_label}
                  onChange={(e) =>
                    update({
                      condition_config: { ...draft.condition_config!, false_label: e.target.value },
                    })
                  }
                />
              </Field>
            </div>
          </>
        )}

        {/* ── Notification fields ────────────────────────── */}
        {nodeType === 'notification' && draft.notification_config && (
          <>
            <Field label="Channel">
              <Select
                value={draft.notification_config.channel}
                onChange={(v) =>
                  update({
                    notification_config: { ...draft.notification_config!, channel: v },
                  })
                }
                options={['telegram', 'sse']}
              />
            </Field>
            <Field label="Recipient">
              <Input
                className="h-8 text-xs"
                value={draft.notification_config.recipient ?? ''}
                placeholder="Optional"
                onChange={(e) =>
                  update({
                    notification_config: { ...draft.notification_config!, recipient: e.target.value || null },
                  })
                }
              />
            </Field>
            <Field label="Message template">
              <Textarea
                className="min-h-[60px] text-xs"
                value={draft.notification_config.message_template}
                onChange={(e) =>
                  update({
                    notification_config: { ...draft.notification_config!, message_template: e.target.value },
                  })
                }
              />
            </Field>
          </>
        )}

        {/* ── Human input fields ─────────────────────────── */}
        {nodeType === 'human_input' && draft.human_input_config && (
          <>
            <Field label="Prompt message">
              <Textarea
                className="min-h-[60px] text-xs"
                value={draft.human_input_config.prompt_message}
                onChange={(e) =>
                  update({
                    human_input_config: { ...draft.human_input_config!, prompt_message: e.target.value },
                  })
                }
              />
            </Field>
            <Field label="Channel">
              <Select
                value={draft.human_input_config.channel}
                onChange={(v) =>
                  update({
                    human_input_config: { ...draft.human_input_config!, channel: v },
                  })
                }
                options={['telegram', 'sse', 'chat']}
              />
            </Field>
            <Field label="Timeout (hours)">
              <Input
                className="h-8 text-xs"
                type="number"
                min={0}
                value={draft.human_input_config.timeout_hours ?? ''}
                placeholder="No timeout"
                onChange={(e) =>
                  update({
                    human_input_config: {
                      ...draft.human_input_config!,
                      timeout_hours: e.target.value ? parseFloat(e.target.value) : null,
                    },
                  })
                }
              />
            </Field>
            <Field label="Default response">
              <Input
                className="h-8 text-xs"
                value={draft.human_input_config.default_response ?? ''}
                placeholder="Optional"
                onChange={(e) =>
                  update({
                    human_input_config: {
                      ...draft.human_input_config!,
                      default_response: e.target.value || null,
                    },
                  })
                }
              />
            </Field>
          </>
        )}
      </div>

      {/* Delete */}
      <Button
        variant="destructive"
        size="sm"
        className="mt-4 w-full gap-1.5 text-xs"
        onClick={onDelete}
      >
        <Trash2 className="h-3.5 w-3.5" />
        Delete Node
      </Button>
    </div>
  )
}

// ── Tiny helpers ────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  )
}
