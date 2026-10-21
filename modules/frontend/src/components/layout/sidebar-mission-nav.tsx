import { NavLink } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { MISSION_NAV_GROUPS, ROUTES } from '@/lib/constants'

export interface SidebarMissionNavProps {
  missionId: string
  /** Pending items that open on the Plan page; shown beside it when above zero. */
  planCount: number
}

/** The active mission's sections, grouped Work / Setup / Observe, indented under its row. */
export function SidebarMissionNav({ missionId, planCount }: SidebarMissionNavProps) {
  return (
    <div className="my-0.5 mb-1.5 ml-[17px] flex flex-col gap-px border-l border-line pl-[9px]">
      {MISSION_NAV_GROUPS.map((group, groupIndex) =>
        group.map((item, itemIndex) => (
          <NavLink
            key={item.label}
            to={item.to(missionId)}
            className={({ isActive }) =>
              cn(
                'flex h-[27px] shrink-0 items-center gap-2.5 rounded-chip px-2 text-sm transition-colors duration-150',
                groupIndex > 0 && itemIndex === 0 && 'mt-2',
                isActive ? 'bg-sidebar-active text-foreground' : 'text-muted-foreground hover:text-foreground',
              )
            }
          >
            <item.icon className="h-3.5 w-3.5" strokeWidth={1.75} />
            {item.label}
            {planCount > 0 && item.to(missionId) === ROUTES.MISSION_PLAN(missionId) && (
              <span aria-label={`${planCount} waiting on the plan`} className="ml-auto font-mono text-2xs text-brand-text">
                {planCount}
              </span>
            )}
          </NavLink>
        )),
      )}
    </div>
  )
}
