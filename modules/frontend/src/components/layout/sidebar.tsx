import { Fragment } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Home, Plus, Shield, type LucideIcon } from 'lucide-react'

import { SidebarFooter } from './sidebar-footer'
import { SidebarMissionNav } from './sidebar-mission-nav'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { missionTone } from '@/lib/status-tone'
import { TONE_DOT } from '@/lib/tone-class'
import { useMissions } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import type { MissionStatus } from '@/types'

const ITEM_BASE =
  'flex h-[30px] shrink-0 items-center gap-2.5 rounded-control px-2.5 text-base transition-colors duration-150'

function itemClass(active: boolean) {
  return cn(ITEM_BASE, active ? 'bg-sidebar-active text-foreground' : 'text-muted-foreground hover:text-foreground')
}

function NavItem({ to, icon: Icon, label, active }: { to: string; icon: LucideIcon; label: string; active: boolean }) {
  return (
    <Link to={to} className={itemClass(active)}>
      <Icon className="h-[15px] w-[15px]" strokeWidth={1.75} />
      {label}
    </Link>
  )
}

export function Sidebar() {
  const { pathname } = useLocation()
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const { data: missions } = useMissions()

  return (
    <aside className="flex h-full w-[236px] shrink-0 flex-col border-r border-border bg-sidebar">
      <Link to={ROUTES.DASHBOARD} className="flex h-[52px] shrink-0 items-center gap-2.5 px-3.5">
        <span className="flex h-[22px] w-[22px] items-center justify-center rounded-md bg-primary font-mono text-[8.5px] font-semibold text-primary-foreground">
          MC
        </span>
        <span className="text-md font-semibold tracking-tight">Mission Control</span>
      </Link>

      <nav className="flex flex-1 flex-col gap-px overflow-y-auto overflow-x-hidden px-2.5 pb-3 pt-1.5">
        <NavItem to={ROUTES.DASHBOARD} icon={Home} label="Home" active={pathname === ROUTES.DASHBOARD} />
        <NavItem to={ROUTES.CATALOG} icon={BookOpen} label="Catalog" active={pathname.startsWith(ROUTES.CATALOG)} />
        {isAdmin && (
          <NavItem to={ROUTES.ADMIN} icon={Shield} label="Admin" active={pathname.startsWith(ROUTES.ADMIN)} />
        )}

        <div className="flex items-center justify-between px-2.5 pb-1.5 pt-[18px] text-xs font-medium text-subtle">
          Missions
          <Link
            to="/missions/new"
            aria-label="New mission"
            title="New mission"
            className="rounded-chip p-0.5 transition-colors duration-150 hover:bg-raised hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
          </Link>
        </div>

        {missions?.map((mission) => {
          const active = pathname.startsWith(`/missions/${mission.id}`)
          return (
            <Fragment key={mission.id}>
              <Link to={ROUTES.MISSION(mission.id)} className={itemClass(active)}>
                <span
                  className={cn(
                    'h-[7px] w-[7px] shrink-0 rounded-full',
                    TONE_DOT[missionTone[mission.status as MissionStatus].tone],
                  )}
                />
                <span className="truncate">{mission.name}</span>
              </Link>
              {active && <SidebarMissionNav missionId={mission.id} />}
            </Fragment>
          )
        })}
      </nav>

      <SidebarFooter />
    </aside>
  )
}
