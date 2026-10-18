import { Loader2 } from 'lucide-react'
import { useAdminConfig } from '@/hooks/use-admin'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'

export default function AdminConfigPage() {
  const { data: config, isLoading } = useAdminConfig()

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-lg font-semibold">Platform Configuration</h2>
      <p className="text-sm text-muted-foreground">
        Non-secret configuration values. Read-only view.
      </p>

      {config && (
        <Panel>
          <PanelHeader title="Current Config" />
          <PanelContent>
            <pre className="rounded-md bg-muted/50 p-4 text-xs font-mono overflow-auto max-h-[600px]">
              {JSON.stringify(config, null, 2)}
            </pre>
          </PanelContent>
        </Panel>
      )}
    </div>
  )
}
