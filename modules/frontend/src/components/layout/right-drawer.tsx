import { X } from 'lucide-react'
import { useEscapeKey } from '@/hooks/use-escape-key'
import { useDrawerStore } from '@/stores/drawer'
import { Button } from '@/components/ui/button'
import { Panel, PanelHeader } from '@/components/ui/panel'
import { AgentDetailPanel } from '@/components/drawer/agent-detail-panel'
import { PromptHistoryPanel } from '@/components/drawer/prompt-history-panel'
import { RunEventsPanel } from '@/components/drawer/run-events-panel'

export function RightDrawer() {
  const { isOpen, contentType, close } = useDrawerStore()
  useEscapeKey(close, isOpen)

  if (!isOpen) return null

  return (
    <div className="flex h-full shrink-0 py-gutter pr-gutter">
      <Panel className="flex h-full w-[400px] flex-col overflow-hidden">
        <PanelHeader
          title={<span className="capitalize">{contentType?.replace(/-/g, ' ') ?? 'Details'}</span>}
          actions={
            <Button variant="ghost" size="icon" aria-label="Close panel" onClick={close}>
              <X className="h-4 w-4" />
            </Button>
          }
        />
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          <DrawerContent contentType={contentType} />
        </div>
      </Panel>
    </div>
  )
}

function DrawerContent({ contentType }: { contentType: string | null }) {
  switch (contentType) {
    case 'agent-detail':
      return <AgentDetailPanel />
    case 'prompt-history':
      return <PromptHistoryPanel />
    case 'run-events':
      return <RunEventsPanel />
    default:
      return (
        <p className="text-sm text-muted-foreground">
          {contentType} content goes here
        </p>
      )
  }
}
