import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Plus,
  BookOpen,
  Shield,
  Settings,
  User,
} from 'lucide-react'
import { NotificationDropdown } from './notification-dropdown'
import { cn } from '@/lib/cn'
import { useAuthStore } from '@/stores/auth'
import { useMissions } from '@/hooks/use-missions'
import { ROUTES } from '@/lib/constants'

export function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, isAdmin } = useAuthStore()

  const { data: missions } = useMissions()

  const currentMissionId = user?.current_mission_id

  const isActive = (path: string) => location.pathname === path
  const isMissionActive = (id: string) =>
    location.pathname.startsWith(`/missions/${id}`)

  return (
    <aside className="flex h-full w-60 flex-col border-r bg-card">
      {/* Logo */}
      <div className="flex h-14 items-center px-4">
        <Link to={ROUTES.DASHBOARD} className="text-lg font-bold tracking-tight">
          MISSION CONTROL
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        <SidebarLink
          to={ROUTES.DASHBOARD}
          icon={<LayoutDashboard className="h-4 w-4" />}
          label="Dashboard"
          active={isActive(ROUTES.DASHBOARD)}
        />

        <div className="mt-6 mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Missions
        </div>

        {missions?.map((mission) => (
          <button
            key={mission.id}
            onClick={() => navigate(ROUTES.MISSION_OVERVIEW(mission.id))}
            className={cn(
              'flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent',
              isMissionActive(mission.id) && 'bg-accent text-accent-foreground',
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                isMissionActive(mission.id)
                  ? 'bg-primary'
                  : currentMissionId === mission.id
                    ? 'bg-primary/50'
                    : 'bg-muted-foreground/30',
              )}
            />
            <span className="truncate">{mission.name}</span>
          </button>
        ))}

        <button
          onClick={() => navigate('/missions/new')}
          className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <Plus className="h-4 w-4" />
          New Mission
        </button>

        <div className="mt-6 mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Platform
        </div>

        <SidebarLink
          to={ROUTES.CATALOG}
          icon={<BookOpen className="h-4 w-4" />}
          label="Catalog"
          active={isActive(ROUTES.CATALOG)}
        />

        {isAdmin && (
          <SidebarLink
            to={ROUTES.ADMIN}
            icon={<Shield className="h-4 w-4" />}
            label="Admin"
            active={location.pathname.startsWith(ROUTES.ADMIN)}
          />
        )}
      </nav>

      {/* Footer */}
      <div className="flex items-center justify-around border-t p-3">
        <button
          onClick={() => navigate(ROUTES.PROFILE)}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <Settings className="h-4 w-4" />
        </button>

        <NotificationDropdown />

        <button
          onClick={() => navigate(ROUTES.PROFILE)}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <User className="h-4 w-4" />
        </button>
      </div>
    </aside>
  )
}

function SidebarLink({
  to,
  icon,
  label,
  active,
}: {
  to: string
  icon: React.ReactNode
  label: string
  active: boolean
}) {
  return (
    <Link
      to={to}
      className={cn(
        'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent',
        active && 'bg-accent text-accent-foreground font-medium',
      )}
    >
      {icon}
      {label}
    </Link>
  )
}
