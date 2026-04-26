import { X, Bot, GitBranch, Bell } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { WorkflowStep } from '@/types'

interface StepDetailProps {
  step: WorkflowStep
  onClose: () => void
}

export function StepDetail({ step, onClose }: StepDetailProps) {
  const nodeType = step.node_type ?? 'agent_step'
  const NodeIcon = nodeType === 'condition' ? GitBranch
    : nodeType === 'notification' ? Bell
    : Bot

  return (
    <div className="rounded-lg border bg-card p-4 shadow-md">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <NodeIcon className="h-4 w-4 text-muted-foreground" />
          <h4 className="font-semibold">{step.id}</h4>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <Badge variant="outline" className="mb-3 text-[10px]">
        {nodeType.replace('_', ' ')}
      </Badge>

      {step.description && (
        <p className="mb-3 text-sm text-muted-foreground">{step.description}</p>
      )}

      <div className="space-y-2 text-sm">
        {/* Agent step fields */}
        {nodeType === 'agent_step' && step.capability && (
          <>
            <Row label="Capability" value={step.capability} />
            <Row label="Environment" value={step.environment} />
            <Row label="Termination" value={step.termination} />
            <Row label="Max Refinement" value={String(step.max_refinement_rounds)} />
            {step.cost_ceiling_usd && (
              <Row label="Cost Ceiling" value={`$${step.cost_ceiling_usd}`} />
            )}
            {step.timeout_seconds && (
              <Row label="Timeout" value={`${step.timeout_seconds}s`} />
            )}
          </>
        )}

        {/* Condition config */}
        {nodeType === 'condition' && step.condition_config && (
          <div className="space-y-2">
            <div>
              <span className="text-xs font-medium text-muted-foreground">Expression</span>
              <pre className="mt-1 rounded-md bg-muted/50 p-2 font-mono text-xs leading-relaxed">
                {step.condition_config.expression}
              </pre>
            </div>
            <div className="flex gap-4">
              <div>
                <span className="text-xs text-muted-foreground">True →</span>
                <span className="ml-1 text-xs font-medium text-emerald-500">
                  {step.condition_config.true_label}
                </span>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">False →</span>
                <span className="ml-1 text-xs font-medium text-red-400">
                  {step.condition_config.false_label}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Notification config */}
        {nodeType === 'notification' && step.notification_config && (
          <div className="space-y-2">
            <Row label="Channel" value={step.notification_config.channel} />
            {step.notification_config.recipient && (
              <Row label="Recipient" value={step.notification_config.recipient} />
            )}
            <div>
              <span className="text-xs font-medium text-muted-foreground">Message</span>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/50 p-2 font-mono text-xs leading-relaxed">
                {step.notification_config.message_template}
              </pre>
            </div>
          </div>
        )}

        {step.depends_on.length > 0 && (
          <div>
            <span className="text-xs font-medium text-muted-foreground">
              Depends On
            </span>
            <div className="mt-1 flex flex-wrap gap-1">
              {step.depends_on.map((d) => (
                <Badge key={d} variant="outline" className="text-[10px]">
                  {d}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {step.output_mapping && (
          <div>
            <span className="text-xs font-medium text-muted-foreground">
              Outputs
            </span>
            <div className="mt-1 space-y-0.5">
              {step.output_mapping.summary_key && (
                <p className="text-xs">
                  summary → <code>{step.output_mapping.summary_key}</code>
                </p>
              )}
              {step.output_mapping.field_mappings.map((fm) => (
                <p key={fm.target_key} className="text-xs">
                  {fm.source_task}.{fm.source_field} → <code>{fm.target_key}</code>
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-medium">{value}</span>
    </div>
  )
}
