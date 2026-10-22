/**
 * ArtifactViewerPanel — right panel for rendering artifact content.
 *
 * Handles all content types: markdown (direct render), code (fenced
 * block with language), json (formatted code block), text (plain).
 * The header carries the type, title, agent, timestamp and Copy/Download.
 */

import { Package } from 'lucide-react'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { EmptyState } from '@/components/ui/empty-state'
import { Panel } from '@/components/ui/panel'
import { ArtifactViewerHeader } from '@/components/workspace/artifact-viewer-header'
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
      <Panel className="flex min-w-0 flex-1 items-center justify-center">
        <EmptyState
          icon={<Package className="h-4 w-4" />}
          title="Select an artifact to view"
          description="Its content appears here."
        />
      </Panel>
    )
  }

  return (
    <Panel className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <ArtifactViewerHeader artifact={artifact} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[700px] px-8 pb-10 pt-4">
          <MarkdownRenderer content={formatContent(artifact)} className="text-md text-text-2" />
        </div>
      </div>
    </Panel>
  )
}
