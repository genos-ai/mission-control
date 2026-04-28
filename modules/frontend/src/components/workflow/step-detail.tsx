/**
 * StepDetail — editable config panel for a selected workflow node.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { X, Bot, GitBranch, Bell, UserRound, Wrench, Sparkles, Split, Merge, Layers, Trash2, ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCatalog } from '@/hooks/use-catalog'
import { useMissionWorkflows } from '@/hooks/use-workflows'
import { ROUTES } from '@/lib/constants'
import { VariableAutocomplete } from './variable-autocomplete'
import type { WorkflowStep } from '@/types'

interface StepDetailProps {
  step: WorkflowStep
  onClose: () => void
  onUpdate: (updated: WorkflowStep) => void
  onDelete: () => void
  missionId?: string
  currentWorkflowId?: string
  upstreamNodeIds?: string[]
}

export function StepDetail({ step, onClose, onUpdate, onDelete, missionId, currentWorkflowId, upstreamNodeIds = [] }: StepDetailProps) {
  const navigate = useNavigate()
  const [draft, setDraft] = useState<WorkflowStep>(step)
  const { data: agents = [] } = useCatalog()
  const { data: workflows = [] } = useMissionWorkflows(missionId)

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
    : nodeType === 'tool_call' ? Wrench
    : nodeType === 'llm_call' ? Sparkles
    : nodeType === 'branch' ? Split
    : nodeType === 'merge' ? Merge
    : nodeType === 'sub_workflow' ? Layers
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
            <Field label="Agent">
              <select
                value={draft.capability ?? ''}
                onChange={(e) => update({ capability: e.target.value || null })}
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select an agent…</option>
                {agents.map((a) => (
                  <option key={a.agent_name} value={a.agent_name}>
                    {a.agent_name}
                  </option>
                ))}
              </select>
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
            <Field label="Condition (skip when false)">
              <VariableAutocomplete
                className="min-h-[40px] font-mono text-xs"
                value={draft.condition ?? ''}
                onChange={(v) => update({ condition: v || null })}
                upstreamNodeIds={upstreamNodeIds}
                templateMode={false}
                placeholder='@context.target_path != null'
              />
            </Field>
          </>
        )}

        {/* ── Condition fields ───────────────────────────── */}
        {nodeType === 'condition' && draft.condition_config && (
          <>
            <Field label="Expression">
              <VariableAutocomplete
                className="min-h-[50px] font-mono text-xs"
                value={draft.condition_config.expression}
                onChange={(v) =>
                  update({
                    condition_config: { ...draft.condition_config!, expression: v },
                  })
                }
                upstreamNodeIds={upstreamNodeIds}
                templateMode={false}
                placeholder="@node.step-id.field >= 0.7"
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
              <VariableAutocomplete
                className="min-h-[60px] text-xs"
                value={draft.notification_config.message_template}
                onChange={(v) =>
                  update({
                    notification_config: { ...draft.notification_config!, message_template: v },
                  })
                }
                upstreamNodeIds={upstreamNodeIds}
                placeholder="Use {{@node.step-id.field}} for variables"
              />
            </Field>
          </>
        )}

        {/* ── Human input fields ─────────────────────────── */}
        {nodeType === 'human_input' && draft.human_input_config && (
          <>
            <Field label="Prompt message">
              <VariableAutocomplete
                className="min-h-[60px] text-xs"
                value={draft.human_input_config.prompt_message}
                onChange={(v) =>
                  update({
                    human_input_config: { ...draft.human_input_config!, prompt_message: v },
                  })
                }
                upstreamNodeIds={upstreamNodeIds}
                placeholder="Use {{@node.step-id.field}} for variables"
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
            <Field label="Choices (one per line)">
              <Textarea
                className="min-h-[50px] text-xs"
                value={(draft.human_input_config.choices ?? []).join('\n')}
                placeholder="Leave empty for free text"
                onChange={(e) => {
                  const lines = e.target.value.split('\n').filter((l) => l.trim())
                  update({
                    human_input_config: {
                      ...draft.human_input_config!,
                      choices: lines.length > 0 ? lines : null,
                    },
                  })
                }}
              />
            </Field>
          </>
        )}

        {/* ── Tool call fields ─────────────────────────────── */}
        {nodeType === 'tool_call' && draft.tool_call_config && (
          <>
            <Field label="Tool name">
              <Input
                className="h-8 text-xs"
                value={draft.tool_call_config.tool_name}
                placeholder="e.g. search_web"
                onChange={(e) =>
                  update({
                    tool_call_config: { ...draft.tool_call_config!, tool_name: e.target.value },
                  })
                }
              />
            </Field>
            <Field label="Arguments (JSON)">
              <Textarea
                className="min-h-[80px] font-mono text-xs"
                value={JSON.stringify(draft.tool_call_config.tool_args, null, 2)}
                placeholder='{"query": "{{@node.step-id.output}}"}'
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value)
                    update({
                      tool_call_config: { ...draft.tool_call_config!, tool_args: parsed },
                    })
                  } catch {
                    // Allow typing invalid JSON mid-edit
                  }
                }}
              />
            </Field>
          </>
        )}

        {/* ── LLM call fields ──────────────────────────────── */}
        {nodeType === 'llm_call' && draft.llm_call_config && (
          <>
            <Field label="Model">
              <Input
                className="h-8 text-xs"
                value={draft.llm_call_config.model}
                placeholder="e.g. copilot:claude-haiku-4.5"
                onChange={(e) =>
                  update({
                    llm_call_config: { ...draft.llm_call_config!, model: e.target.value },
                  })
                }
              />
            </Field>
            <Field label="System prompt">
              <Textarea
                className="min-h-[40px] text-xs"
                value={draft.llm_call_config.system_prompt ?? ''}
                placeholder="Optional system instructions"
                onChange={(e) =>
                  update({
                    llm_call_config: { ...draft.llm_call_config!, system_prompt: e.target.value || null },
                  })
                }
              />
            </Field>
            <Field label="Prompt template">
              <VariableAutocomplete
                className="min-h-[80px] text-xs"
                value={draft.llm_call_config.prompt_template}
                placeholder="Use {{@node.step-id.field}} for variables"
                onChange={(v) =>
                  update({
                    llm_call_config: { ...draft.llm_call_config!, prompt_template: v },
                  })
                }
                upstreamNodeIds={upstreamNodeIds}
              />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Temperature">
                <Input
                  className="h-8 text-xs"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={draft.llm_call_config.temperature}
                  onChange={(e) =>
                    update({
                      llm_call_config: { ...draft.llm_call_config!, temperature: parseFloat(e.target.value) || 0 },
                    })
                  }
                />
              </Field>
              <Field label="Max tokens">
                <Input
                  className="h-8 text-xs"
                  type="number"
                  min={1}
                  value={draft.llm_call_config.max_tokens ?? ''}
                  placeholder="Default"
                  onChange={(e) =>
                    update({
                      llm_call_config: {
                        ...draft.llm_call_config!,
                        max_tokens: e.target.value ? parseInt(e.target.value) : null,
                      },
                    })
                  }
                />
              </Field>
            </div>
            <Field label="Structured output (JSON schema)">
              <Textarea
                className="min-h-[60px] font-mono text-xs"
                value={draft.llm_call_config.structured_output ? JSON.stringify(draft.llm_call_config.structured_output, null, 2) : ''}
                placeholder="Optional JSON schema for structured output"
                onChange={(e) => {
                  if (!e.target.value.trim()) {
                    update({
                      llm_call_config: { ...draft.llm_call_config!, structured_output: null },
                    })
                    return
                  }
                  try {
                    const parsed = JSON.parse(e.target.value)
                    update({
                      llm_call_config: { ...draft.llm_call_config!, structured_output: parsed },
                    })
                  } catch {
                    // Allow typing invalid JSON mid-edit
                  }
                }}
              />
            </Field>
          </>
        )}
        {/* ── Branch fields ──────────────────────────────────── */}
        {nodeType === 'branch' && (
          <p className="text-xs text-muted-foreground">
            Fork node — splits into parallel paths. Connect outgoing edges to downstream steps.
          </p>
        )}

        {/* ── Merge fields ──────────────────────────────────── */}
        {nodeType === 'merge' && (
          <Field label="Strategy">
            <Select
              value={draft.merge_config?.strategy ?? 'wait_all'}
              onChange={(v) =>
                update({
                  merge_config: { ...draft.merge_config, strategy: v },
                })
              }
              options={['wait_all', 'wait_any']}
            />
          </Field>
        )}

        {/* ── Sub-workflow fields ──────────────────────────── */}
        {nodeType === 'sub_workflow' && draft.sub_workflow_config && (
          <>
            <Field label="Target workflow">
              <select
                value={draft.sub_workflow_config.workflow_id}
                onChange={(e) => {
                  const wf = workflows.find((w) => w.id === e.target.value)
                  update({
                    sub_workflow_config: {
                      ...draft.sub_workflow_config!,
                      workflow_id: e.target.value,
                      workflow_name: wf?.name ?? '',
                    },
                  })
                }}
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select a workflow…</option>
                {workflows
                  .filter((w) => w.id !== currentWorkflowId)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
              </select>
            </Field>
            {draft.sub_workflow_config.workflow_id && missionId && (
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-1.5 text-xs"
                onClick={() =>
                  navigate(ROUTES.MISSION_WORKFLOW_EDIT(missionId, draft.sub_workflow_config!.workflow_id))
                }
              >
                <ExternalLink className="h-3 w-3" />
                Open Sub-Workflow
              </Button>
            )}
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="pass-context"
                checked={draft.sub_workflow_config.pass_context}
                onChange={(e) =>
                  update({
                    sub_workflow_config: { ...draft.sub_workflow_config!, pass_context: e.target.checked },
                  })
                }
                className="rounded border-input"
              />
              <label htmlFor="pass-context" className="text-xs text-muted-foreground">
                Pass parent context to child
              </label>
            </div>
            <Field label="Max depth">
              <Input
                className="h-8 text-xs"
                type="number"
                min={1}
                max={10}
                value={draft.sub_workflow_config.max_depth}
                onChange={(e) =>
                  update({
                    sub_workflow_config: {
                      ...draft.sub_workflow_config!,
                      max_depth: parseInt(e.target.value) || 3,
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
