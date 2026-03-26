import { X } from 'lucide-react'
import { useDrawerStore } from '@/stores/drawer'
import { Button } from '@/components/ui/button'
import { AgentDetailPanel } from '@/components/drawer/agent-detail-panel'
import { PromptHistoryPanel } from '@/components/drawer/prompt-history-panel'
import { ArchitectChatPanel } from '@/components/drawer/architect-chat-panel'
import { EventLogPanel } from '@/components/drawer/event-log-panel'
import { OutputPreviewPanel } from '@/components/drawer/output-preview-panel'
import { CostBreakdownPanel } from '@/components/drawer/cost-breakdown-panel'
import { RunEventsPanel } from '@/components/drawer/run-events-panel'

export function RightDrawer() {
  const { isOpen, contentType, close } = useDrawerStore()

  if (!isOpen) return null

  return (
    <div className="flex h-full w-[400px] flex-shrink-0 flex-col border-l bg-card">
      <div className="flex h-10 items-center justify-between border-b px-4">
        <span className="text-sm font-medium capitalize">
          {contentType?.replace(/-/g, ' ') ?? 'Details'}
        </span>
        <Button variant="ghost" size="icon" onClick={close} className="h-7 w-7">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <DrawerContent contentType={contentType} />
      </div>
    </div>
  )
}

function DrawerContent({ contentType }: { contentType: string | null }) {
  switch (contentType) {
    case 'agent-detail':
      return <AgentDetailPanel />
    case 'prompt-history':
      return <PromptHistoryPanel />
    case 'architect-chat':
      return <ArchitectChatPanel />
    case 'event-log':
      return <EventLogPanel />
    case 'output-preview':
      return <OutputPreviewPanel />
    case 'cost-breakdown':
      return <CostBreakdownPanel />
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
