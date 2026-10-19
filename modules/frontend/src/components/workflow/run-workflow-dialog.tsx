import { useState, useCallback } from 'react'
import { X, Play } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useRunWorkflow } from '@/hooks/use-workflows'
import type { WorkflowParameter } from './workflow-editor-types'

interface RunWorkflowDialogProps {
  missionId: string
  workflowName: string
  parameters: WorkflowParameter[]
  onClose: () => void
}

export function RunWorkflowDialog({
  missionId,
  workflowName,
  parameters,
  onClose,
}: RunWorkflowDialogProps) {
  const runMutation = useRunWorkflow(missionId)

  // Initialize form values from parameter defaults
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {}
    for (const p of parameters) {
      if (p.default != null) {
        init[p.key] = p.default
      } else if (p.type === 'boolean') {
        init[p.key] = false
      } else if (p.type === 'number') {
        init[p.key] = p.min ?? 0
      } else {
        init[p.key] = ''
      }
    }
    return init
  })

  const setValue = useCallback((key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    // Validate required fields
    const missing = parameters.filter(
      (p) => p.required && !values[p.key] && values[p.key] !== 0 && values[p.key] !== false,
    )
    if (missing.length > 0) {
      toast.error(`Required: ${missing.map((p) => p.label).join(', ')}`)
      return
    }

    // Build context overrides (only include non-empty values)
    const contextOverrides: Record<string, unknown> = {}
    for (const p of parameters) {
      const val = values[p.key]
      if (val !== '' && val != null) {
        contextOverrides[p.key] = val
      }
    }

    onClose()
    runMutation.mutate(
      { workflowName, contextOverrides },
      {
        onSuccess: () => toast.success('Workflow started'),
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm">
      <Panel
        role="dialog"
        aria-modal="true" aria-label="Run Workflow"
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto p-5 shadow-lg"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-medium">Run Workflow</h3>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {parameters.map((param) => (
            <ParameterField
              key={param.key}
              param={param}
              value={values[param.key]}
              onChange={(val) => setValue(param.key, val)}
            />
          ))}

          {parameters.length === 0 && (
            <p className="text-xs text-muted-foreground">This workflow has no parameters. It will run with default context.</p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={runMutation.isPending}>
              <Play className="h-3 w-3" />
              {runMutation.isPending ? 'Starting...' : 'Run'}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}

// ---- Parameter field renderer ----

// Matches the shared Input styling so the native <select> blends in.
const SELECT_CLASS =
  'flex h-[38px] w-full rounded-md border border-border-strong bg-field px-3 text-md outline-none transition-colors focus:border-brand/60 focus:ring-2 focus:ring-brand/15'

function ParameterField({
  param,
  value,
  onChange,
}: {
  param: WorkflowParameter
  value: unknown
  onChange: (val: unknown) => void
}) {
  const id = `param-${param.key}`

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {param.label}
        {param.required && <span className="ml-0.5 text-danger">*</span>}
      </label>

      {param.description && (
        <p className="text-xs text-subtle">{param.description}</p>
      )}

      {param.type === 'text' && (
        <Textarea
          id={id}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={param.placeholder ?? undefined}
          rows={3}
        />
      )}

      {param.type === 'string' && (
        <Input
          id={id}
          type="text"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={param.placeholder ?? undefined}
        />
      )}

      {param.type === 'number' && (
        <Input
          id={id}
          type="number"
          value={value as number}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          step={param.max && param.max <= 1 ? 0.05 : 1}
        />
      )}

      {param.type === 'boolean' && (
        <Switch checked={!!value} onChange={onChange} label={param.label} />
      )}

      {param.type === 'enum' && param.options && (
        <select
          id={id}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className={SELECT_CLASS}
        >
          {param.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
