import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArtifactListPanel } from '@/components/workspace/artifact-list-panel'
import { ArtifactViewerPanel } from '@/components/workspace/artifact-viewer-panel'
import { useMissionArtifacts } from '@/hooks/use-mission-artifacts'

export default function ArtifactsTab() {
  const { id } = useParams<{ id: string }>()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: artifacts = [], isLoading } = useMissionArtifacts(id!, { limit: 200 })
  const selected = artifacts.find((a) => a.id === selectedId) ?? null

  return (
    <div className="flex h-full min-h-0 gap-gutter px-2 pb-2">
      <ArtifactListPanel
        artifacts={artifacts}
        isLoading={isLoading}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
      <ArtifactViewerPanel artifact={selected} />
    </div>
  )
}
