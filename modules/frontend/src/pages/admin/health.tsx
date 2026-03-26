import { Loader2, CheckCircle, XCircle, RefreshCw } from 'lucide-react'
import { useHealthCheck } from '@/hooks/use-admin'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'


export default function AdminHealthPage() {
  const { data: health, isLoading, refetch, isFetching } = useHealthCheck()

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">System Health</h2>
          {health && (
            <Badge
              variant={health.status === 'healthy' ? 'success' : 'destructive'}
            >
              {health.status}
            </Badge>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 mr-1" />
          )}
          Refresh
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Auto-refreshes every 30 seconds.
      </p>

      {health?.checks && (
        <div className="space-y-2">
          {Object.entries(health.checks).map(([name, check]) => (
            <Card key={name}>
              <CardContent className="flex items-center justify-between py-3 px-4">
                <div className="flex items-center gap-3">
                  {check.status === 'healthy' || check.status === 'ok' ? (
                    <CheckCircle className="h-4 w-4 text-emerald-500" />
                  ) : (
                    <XCircle className="h-4 w-4 text-destructive" />
                  )}
                  <span className="text-sm font-medium">{name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {check.latency_ms != null && (
                    <span>{check.latency_ms.toFixed(0)}ms</span>
                  )}
                  <Badge
                    variant={
                      check.status === 'healthy' || check.status === 'ok'
                        ? 'success'
                        : 'destructive'
                    }
                    className="text-[9px]"
                  >
                    {check.status}
                  </Badge>
                  {check.error && (
                    <span className="text-destructive truncate max-w-[200px]">
                      {check.error}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
