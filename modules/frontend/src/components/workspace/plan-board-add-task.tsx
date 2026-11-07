import { useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import toast from 'react-hot-toast'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { useAddPlanTask } from '@/hooks/use-mission-plan'
import { useTeam } from '@/hooks/use-team'

const FIELD =
  'w-full rounded-md border border-border-strong bg-field px-2.5 py-1.5 text-xs outline-none transition-colors placeholder:text-subtle focus:border-brand/60 focus:ring-2 focus:ring-brand/15 disabled:opacity-50'

export interface AddTaskProps {
  missionId: string
}

/** "+ Add task" row that opens an inline form. New tasks always enter as proposed. */
export function AddTask({ missionId }: AddTaskProps) {
  const [open, setOpen] = useState(false)

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex h-[34px] w-full items-center gap-1.5 rounded-md px-2 text-xs text-subtle transition-colors duration-150 hover:bg-raised hover:text-foreground"
      >
        <Plus className="h-3 w-3" />
        Add task
      </button>
    )
  }
  return <AddTaskForm missionId={missionId} onDone={() => setOpen(false)} />
}

function AddTaskForm({ missionId, onDone }: AddTaskProps & { onDone: () => void }) {
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
    if (e.key === 'Escape') {
      onDone()
      return
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  return (
    <div className="space-y-2 rounded-card bg-raised p-2.5">
      <Textarea
        autoFocus
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Task description…"
        rows={2}
        className="resize-none border-panel-border bg-field text-xs"
        disabled={addTask.isPending}
      />
      {agentNames.length > 0 ? (
        <Select
          aria-label="Agent"
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          disabled={addTask.isPending}
          size="sm"
          className="h-auto px-2.5 py-1.5"
        >
          <option value="">Select agent…</option>
          {agentNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </Select>
      ) : (
        <input
          aria-label="Agent name"
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Agent name (e.g. code.agent)"
          className={FIELD}
          disabled={addTask.isPending}
        />
      )}
      <div className="flex items-center justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onDone} disabled={addTask.isPending}>
          Cancel
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={addTask.isPending || !description.trim() || !agentInput.trim()}>
          {addTask.isPending ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" /> : 'Add task'}
        </Button>
      </div>
    </div>
  )
}
