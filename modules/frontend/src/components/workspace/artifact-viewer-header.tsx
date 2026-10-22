/**
 * ArtifactViewerHeader — type, title, provenance and actions for the artifact
 * on screen. The provenance sits under the title so a narrow panel keeps it.
 */

import { StatusPill } from '@/components/ui/status-pill'
import { ArtifactViewerActions } from '@/components/workspace/artifact-viewer-actions'
import { formatUtc } from '@/lib/format-date'
import { agentShortName, statusLabel } from '@/lib/format'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'

export function ArtifactViewerHeader({ artifact }: { artifact: MissionArtifact }) {
  const meta = [agentShortName(artifact.agent_id), formatUtc(artifact.created_at), artifact.language]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="flex shrink-0 items-center gap-3 px-5 py-3">
      <StatusPill tone="violet" dot={false} className="shrink-0">
        {statusLabel(artifact.artifact_type)}
      </StatusPill>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h2 className="truncate text-md font-medium" title={artifact.title}>
          {artifact.title}
        </h2>
        <span className="truncate text-xs text-subtle" title={meta}>
          {meta}
        </span>
      </div>
      <ArtifactViewerActions artifact={artifact} />
    </div>
  )
}
