import { Loader2 } from 'lucide-react'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { agentShortName } from '@/lib/format'
import type { StreamingArtifact } from '@/stores/workspace'

export function StreamingArtifactCard({ streaming }: { streaming: StreamingArtifact }) {
  return (
    <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
        <span className="font-medium text-amber-400">{agentShortName(streaming.agentId)}</span>
        <span className="text-muted-foreground/60">writing…</span>
      </div>
      <div className="max-h-48 overflow-y-auto">
        <MarkdownRenderer content={streaming.content} className="text-[11px]" />
      </div>
    </div>
  )
}
