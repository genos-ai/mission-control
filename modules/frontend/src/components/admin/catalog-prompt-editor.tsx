import { useEffect, useState } from 'react'
import { useCatalogAgent } from '@/hooks/use-catalog'
import { Button } from '@/components/ui/button'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'

/** Edits one agent's system prompt, loaded from the catalogue detail. */
export function CatalogPromptEditor({
  agentName,
  onSave,
  saving,
  onClose,
}: {
  agentName: string
  onSave: (content: string) => void
  saving: boolean
  onClose: () => void
}) {
  const { data: agentDetail, isLoading } = useCatalogAgent(agentName)
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)

  // Populate with existing prompt once loaded
  useEffect(() => {
    if (agentDetail && !loaded) {
      setContent(agentDetail.system_prompt ?? '')
      setLoaded(true)
    }
  }, [agentDetail, loaded])

  return (
    <Panel className="border-brand/30">
      <PanelHeader
        title={`System prompt: ${agentName}`}
        actions={
          <>
            <Button size="sm" onClick={() => onSave(content)} disabled={saving || isLoading}>
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </>
        }
      />
      <PanelContent>
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : (
          <Textarea
            aria-label={`System prompt for ${agentName}`}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
            className="font-mono text-xs"
          />
        )}
      </PanelContent>
    </Panel>
  )
}
