import { useId } from 'react'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { type NewAgentDraft } from '@/components/admin/catalog-new-agent'
import { CATALOG_SELECT_CLASS } from '@/components/admin/catalog-select-class'

/** The "new agent" form above the catalogue list. The draft lives in the page so it survives Cancel. */
export function CatalogCreateForm({
  draft,
  onChange,
  onCreate,
  onCancel,
  creating,
}: {
  draft: NewAgentDraft
  onChange: (next: NewAgentDraft) => void
  onCreate: () => void
  onCancel: () => void
  creating: boolean
}) {
  const id = useId()

  return (
    <Panel>
      <PanelHeader title="Create agent" />
      <PanelContent className="flex flex-col gap-3">
        <div className="grid grid-cols-[minmax(0,1fr)_180px] gap-3">
          <Field label="Agent name" htmlFor={`${id}-name`}>
            <Input
              id={`${id}-name`}
              value={draft.agent_name}
              onChange={(e) => onChange({ ...draft, agent_name: e.target.value })}
              placeholder="Agent name"
            />
          </Field>
          <Field label="Type" htmlFor={`${id}-type`}>
            <select
              id={`${id}-type`}
              value={draft.agent_type}
              onChange={(e) => onChange({ ...draft, agent_type: e.target.value as NewAgentDraft['agent_type'] })}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="vertical">Vertical</option>
              <option value="horizontal">Horizontal</option>
              <option value="system">System</option>
            </select>
          </Field>
        </div>
        <Field label="Description" htmlFor={`${id}-description`}>
          <Textarea
            id={`${id}-description`}
            value={draft.description}
            onChange={(e) => onChange({ ...draft, description: e.target.value })}
            placeholder="Description"
            rows={2}
          />
        </Field>
        <div className="flex items-center gap-2">
          <Button onClick={onCreate} disabled={!draft.agent_name.trim() || creating}>
            Create
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </PanelContent>
    </Panel>
  )
}
