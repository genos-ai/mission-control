import { Loader2 } from 'lucide-react'
import { useAdminConfig } from '@/hooks/use-admin'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

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
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Current Config</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="rounded-md bg-muted/50 p-4 text-xs font-mono overflow-auto max-h-[600px]">
              {JSON.stringify(config, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
