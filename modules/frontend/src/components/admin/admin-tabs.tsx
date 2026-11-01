import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'

const tabs = [
  { label: 'Catalog', path: ROUTES.ADMIN_CATALOG },
  { label: 'Metrics', path: ROUTES.ADMIN_METRICS },
  { label: 'Token Economics', path: ROUTES.ADMIN_TOKEN_ECONOMICS },
  { label: 'Config', path: ROUTES.ADMIN_CONFIG },
  { label: 'Health', path: ROUTES.ADMIN_HEALTH },
  { label: 'Users', path: ROUTES.ADMIN_USERS },
]

/** The one underline tab row the app keeps; it sits inside the page column, not full-bleed. */
export function AdminTabs() {
  return (
    <nav aria-label="Admin sections" className="flex gap-0.5 border-b border-border">
      {tabs.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          className={({ isActive }) =>
            cn(
              '-mb-px shrink-0 whitespace-nowrap border-b-[1.5px] px-2.5 pb-2.5 pt-2 text-sm transition-colors',
              isActive
                ? 'border-foreground text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
