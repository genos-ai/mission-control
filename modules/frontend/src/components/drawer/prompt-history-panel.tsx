import { formatUtc } from '@/lib/format-date'
import { usePromptHistory } from '@/hooks/use-team'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

export function PromptHistoryPanel() {
  const { context } = useDrawerStore()
  const missionId = context.missionId as string | undefined
  const memberId = context.memberId as string | undefined

  const { data, isLoading } = usePromptHistory(missionId, memberId)

  if (isLoading) return <Spinner />

  if (!data?.versions?.length) {
    return (
      <p className="text-sm text-muted-foreground">No prompt history yet.</p>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        {data.versions.length} version{data.versions.length !== 1 ? 's' : ''}
      </p>

      {data.versions.map((v) => (
        <div
          key={v.version}
          className="rounded-lg border p-3"
        >
          <div className="mb-2 flex items-center justify-between">
            <Badge variant="outline">v{v.version}</Badge>
            <span className="text-[11px] text-muted-foreground">
              {formatUtc(v.created_at)}
            </span>
          </div>

          <MarkdownRenderer content={v.content} />

          {v.change_reason && (
            <p className="mt-2 text-xs text-muted-foreground italic">
              {v.change_reason}
            </p>
          )}

          <p className="mt-1 text-[11px] text-muted-foreground">
            by {v.changed_by}
          </p>
        </div>
      ))}
    </div>
  )
}
