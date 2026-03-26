import { useDrawerStore } from '@/stores/drawer'

export function OutputPreviewPanel() {
  const { context } = useDrawerStore()
  const content = context.content as Record<string, unknown> | undefined

  if (!content) {
    return <p className="text-sm text-muted-foreground">No output available.</p>
  }

  return (
    <div className="space-y-3">
      <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm leading-relaxed">
        {JSON.stringify(content, null, 2)}
      </pre>
    </div>
  )
}
