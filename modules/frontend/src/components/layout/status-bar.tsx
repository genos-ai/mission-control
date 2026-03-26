import { useExecutions } from '@/hooks/use-executions'

export function StatusBar() {
  const { data } = useExecutions({ status: 'running', limit: 5 })
  const activeCount = data?.executions?.length ?? 0

  return (
    <div className="flex h-8 items-center justify-between border-t bg-card px-4 text-xs text-muted-foreground">
      <span>
        {activeCount > 0
          ? `${activeCount} active run${activeCount !== 1 ? 's' : ''}`
          : 'All quiet'}
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            activeCount > 0 ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'
          }`}
        />
        {activeCount > 0 ? 'Running' : 'Connected'}
      </span>
    </div>
  )
}
