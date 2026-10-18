/**
 * ArtifactViewerPanel — center panel for rendering artifact content.
 *
 * Handles all content types: markdown (direct render), code (fenced
 * block with language), json (formatted code block), text (plain).
 * Shows metadata header with title, type badge, agent, and timestamp.
 */

import { Package } from 'lucide-react'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { Badge } from '@/components/ui/badge'
import { formatUtc } from '@/lib/format-date'
import { agentShortName } from '@/lib/format'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'

function formatContent(artifact: MissionArtifact): string {
  const raw = artifact.content_text ?? ''
  if (!raw) return '*No content available.*'

  switch (artifact.content_type) {
    case 'code':
      return `\`\`\`${artifact.language ?? ''}\n${raw}\n\`\`\``
    case 'json':
      try {
        return `\`\`\`json\n${JSON.stringify(JSON.parse(raw), null, 2)}\n\`\`\``
      } catch {
        return `\`\`\`json\n${raw}\n\`\`\``
      }
    default:
      return raw
  }
}

export function ArtifactViewerPanel({ artifact }: { artifact: MissionArtifact | null }) {
  if (!artifact) {
    return (
      <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 px-5 py-8">
        <Package className="h-8 w-8 text-muted-foreground/20" />
        <p className="text-center text-sm text-muted-foreground/60">
          Select an artifact to view
        </p>
      </div>
    )
  }

  const agentShort = agentShortName(artifact.agent_id)

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* Header */}
      <div className="shrink-0 border-b px-5 py-3">
        <h2 className="text-sm font-semibold leading-snug">{artifact.title}</h2>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground/70">
          <Badge>
            {artifact.artifact_type}
          </Badge>
          <span>{agentShort}</span>
          <span>·</span>
          <span>{formatUtc(artifact.created_at)}</span>
          {artifact.language && (
            <>
              <span>·</span>
              <span>{artifact.language}</span>
            </>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <MarkdownRenderer content={formatContent(artifact)} className="text-sm" />
      </div>
    </div>
  )
}
