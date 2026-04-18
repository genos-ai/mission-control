import {
  Loader2,
  ChevronRight,
  ChevronDown,
  Package,
} from 'lucide-react'
import { formatUtc } from '@/lib/format-date'
import { useWorkspaceStore, type StreamingArtifact } from '@/stores/workspace'
import { useMissionArtifacts, type MissionArtifact } from '@/hooks/use-mission-artifacts'
import { useResizable } from '@/hooks/use-resizable'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

export function ArtifactsPanel({ missionId, onClose }: { missionId: string; onClose: () => void }) {
  // Durable artifacts via react-query (Plan 43). SSE invalidation wired
  // in layout.tsx — the query refetches when mission.artifact.found
  // fires, so newly persisted rows appear live without a page refresh.
  const { data: artifacts = [], isLoading } = useMissionArtifacts(missionId)
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  const hasContent = streaming || artifacts.length > 0
  const { width, onMouseDown } = useResizable(280)

  return (
    <div className="relative flex shrink-0 flex-col border-l" style={{ width }}>
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/20 transition-colors z-10"
      />
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium">Artifacts</span>
          {streaming && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
              live
            </span>
          )}
          {!streaming && artifacts.length > 0 && (
            <span className="text-[10px] text-muted-foreground/60">
              {artifacts.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && !streaming ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground/50" />
          </div>
        ) : !hasContent ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 py-8">
            <Package className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs leading-relaxed text-muted-foreground/70">
              No artifacts yet.
            </p>
            <p className="max-w-[220px] text-center text-[11px] leading-relaxed text-muted-foreground/50">
              Artifacts appear here when agents produce reports, findings, or code during a run. They are persisted across sessions and survive backend restarts.
            </p>
          </div>
        ) : (
          <div className="space-y-px p-2">
            {streaming && <StreamingArtifactCard streaming={streaming} />}
            {artifacts.map((a) => (
              <ArtifactCard key={a.id} artifact={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function StreamingArtifactCard({ streaming }: { streaming: StreamingArtifact }) {
  const agentShort = streaming.agentId.endsWith('.agent')
    ? streaming.agentId.slice(0, -6)
    : streaming.agentId
  return (
    <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
        <span className="font-medium text-amber-400">{agentShort}</span>
        <span className="text-muted-foreground/60">writing…</span>
      </div>
      <div className="max-h-48 overflow-y-auto">
        <MarkdownRenderer content={streaming.content} className="text-[11px]" />
      </div>
    </div>
  )
}

export function ArtifactCard({ artifact }: { artifact: MissionArtifact }) {
  const content = artifact.content_text ?? ''
  const agentShort = artifact.agent_id.endsWith('.agent')
    ? artifact.agent_id.slice(0, -6)
    : artifact.agent_id
  return (
    <details className="group rounded border border-violet-500/15 bg-violet-500/5 p-2 text-xs">
      <summary className="flex cursor-pointer list-none items-start gap-1.5">
        <Package className="mt-0.5 h-3 w-3 shrink-0 text-violet-400" />
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-snug">{artifact.title}</p>
          <p className="text-[10px] text-muted-foreground/60">
            {agentShort}
            {' · '}{artifact.artifact_type}
            {' · '}{formatUtc(artifact.created_at)}
          </p>
        </div>
        <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 border-t border-violet-500/15 pt-2">
        <MarkdownRenderer content={content} className="text-xs" />
      </div>
    </details>
  )
}
