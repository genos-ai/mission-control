import { useState, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Archive, MoreHorizontal, Plus, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Menu, type MenuItem } from '@/components/ui/menu'
import { Panel } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { StatusPill } from '@/components/ui/status-pill'
import { missionKeys, useDeleteMission } from '@/hooks/use-missions'
import { api } from '@/lib/api'
import { ROUTES } from '@/lib/constants'
import { fmtUsd } from '@/lib/format'
import { formatRelative } from '@/lib/format-date'
import { missionTone } from '@/lib/status-tone'
import type { MissionListItem } from '@/types'

export function MissionCard({ mission, isAdmin }: { mission: MissionListItem; isAdmin: boolean }) {
  const navigate = useNavigate()
  const deleteMission = useDeleteMission()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<'delete' | 'archive' | null>(null)

  async function handleArchive() {
    try {
      await api.patch(`/missions/${mission.id}`, { status: 'archived' })
      toast.success(`${mission.name} archived`)
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Archive failed')
    }
    setDialog(null)
  }

  async function handleDelete() {
    try {
      await deleteMission.mutateAsync(mission.id)
      toast.success(`${mission.name} deleted`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
    setDialog(null)
  }

  const open = () => navigate(ROUTES.MISSION_OVERVIEW(mission.id))

  // Enter on the card opens it; Enter on the menu button inside it must not.
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Enter' && e.target === e.currentTarget) open()
  }

  const ceiling = mission.budget_ceiling_usd
  const canArchive = mission.status !== 'archived'
  const menuItems: MenuItem[] = [
    ...(canArchive ? [{ label: 'Archive', icon: Archive, onSelect: () => setDialog('archive') }] : []),
    { label: 'Delete', icon: Trash2, destructive: true, separatorBefore: canArchive, onSelect: () => setDialog('delete') },
  ]

  return (
    <>
      {dialog === 'delete' && (
        <ConfirmDialog
          title="Delete mission"
          message={`Permanently delete "${mission.name}" and all related data? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          onConfirm={handleDelete}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'archive' && (
        <ConfirmDialog
          title="Archive mission"
          message={`Archive "${mission.name}"? You can restore it later.`}
          confirmLabel="Archive"
          variant="warning"
          onConfirm={handleArchive}
          onCancel={() => setDialog(null)}
        />
      )}
      <Panel
        role="link"
        tabIndex={0}
        onClick={open}
        onKeyDown={onKeyDown}
        className="group flex cursor-pointer flex-col gap-3.5 p-4 transition-colors hover:border-border-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
      >
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-md font-medium">{mission.name}</span>
          {mission.tier === 'platform' && (
            <StatusPill tone="warning" dot={false}>
              platform
            </StatusPill>
          )}
          <StatusPill tone={missionTone[mission.status].tone}>{mission.status}</StatusPill>
          {isAdmin && (
            // The menu sits inside a card that opens the mission on click, so its clicks must not bubble.
            <div onClick={(e) => e.stopPropagation()}>
              <Menu
                label="Mission actions"
                trigger={<MoreHorizontal className="h-3.5 w-3.5" />}
                items={menuItems}
                triggerClassName="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 aria-expanded:opacity-100"
              />
            </div>
          )}
        </div>

        <p className="line-clamp-2 min-h-[38px] text-base text-muted-foreground">{mission.description}</p>

        <div className="mt-auto flex items-end justify-between gap-3 text-xs">
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="font-mono text-text-3">
              {ceiling === null ? fmtUsd(mission.spent_usd) : `${fmtUsd(mission.spent_usd)} of ${fmtUsd(ceiling)}`}
            </span>
            {ceiling !== null && (
              <Progress value={(mission.spent_usd / ceiling) * 100} tone="brand" size="sm" label="Budget used" />
            )}
          </div>
          <span className="shrink-0 text-subtle">created {formatRelative(mission.created_at)}</span>
        </div>
      </Panel>
    </>
  )
}

/** The last tile in the grid: a way to start another mission. */
export function NewMissionTile() {
  return (
    <Link
      to="/missions/new"
      className="flex min-h-[150px] flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-border-strong text-subtle transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      <Plus className="h-5 w-5" />
      <span className="text-base">New mission</span>
    </Link>
  )
}
