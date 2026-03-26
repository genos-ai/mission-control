import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'

const tabs = [
  { label: 'Catalog', path: ROUTES.ADMIN_CATALOG },
  { label: 'Metrics', path: ROUTES.ADMIN_METRICS },
  { label: 'Config', path: ROUTES.ADMIN_CONFIG },
  { label: 'Health', path: ROUTES.ADMIN_HEALTH },
  { label: 'Users', path: ROUTES.ADMIN_USERS },
]

export default function AdminLayout() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex border-b px-4">
        {tabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) =>
              cn(
                'border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}
