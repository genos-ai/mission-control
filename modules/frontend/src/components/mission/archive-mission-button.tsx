import { useState } from 'react'
import { Archive } from 'lucide-react'
import toast from 'react-hot-toast'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useUpdateMission } from '@/hooks/use-missions'

export interface ArchiveMissionButtonProps {
  missionId: string
  missionName: string
  onArchived: () => void
}

/** Archive a mission after confirmation; archived missions can be restored later. */
export function ArchiveMissionButton({ missionId, missionName, onArchived }: ArchiveMissionButtonProps) {
  const [confirming, setConfirming] = useState(false)
  const updateMission = useUpdateMission(missionId)

  function archive() {
    updateMission.mutate(
      { status: 'archived' },
      {
        onSuccess: () => {
          setConfirming(false)
          toast.success(`Archived "${missionName}"`)
          onArchived()
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <>
      <Button variant="secondary" onClick={() => setConfirming(true)}>
        <Archive className="h-3.5 w-3.5" />
        Archive mission
      </Button>
      {confirming && (
        <ConfirmDialog
          title="Archive mission"
          message={`Archive "${missionName}"? You can restore it later.`}
          confirmLabel="Archive"
          variant="warning"
          onConfirm={archive}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  )
}
