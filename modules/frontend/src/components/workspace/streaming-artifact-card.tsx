import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { Spinner } from '@/components/ui/spinner'
import { agentShortName } from '@/lib/format'
import type { StreamingArtifact } from '@/stores/workspace'

/** An artifact an agent is still writing: a raised block with the running-card shimmer along its foot. */
export function StreamingArtifactCard({ streaming }: { streaming: StreamingArtifact }) {
  return (
    <div className="relative overflow-hidden rounded-card bg-raised px-3 pb-3.5 pt-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs">
        <Spinner className="h-3 w-3 text-warning" />
        <span className="truncate font-medium text-warning">{agentShortName(streaming.agentId)}</span>
        <span className="shrink-0 text-subtle">writing…</span>
      </div>
      <div className="max-h-48 overflow-y-auto">
        <MarkdownRenderer content={streaming.content} className="text-xs text-text-2" />
      </div>
      <div
        role="progressbar"
        aria-label="Artifact in progress"
        className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-warning/10"
      >
        <div className="h-full w-2/5 animate-shimmer-x bg-warning motion-reduce:animate-none" />
      </div>
    </div>
  )
}
