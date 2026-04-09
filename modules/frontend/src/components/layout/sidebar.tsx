import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Plus,
  BookOpen,
  Shield,
  Settings,
  LogOut,
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

  // Collapse to icon rail inside any mission workspace
  const isMissionRoute =
    /^\/missions\/[^/]+/.test(location.pathname) &&
    !location.pathname.startsWith('/missions/new')

  if (isMissionRoute) {
    return (
      <aside className="flex h-full w-12 shrink-0 flex-col items-center border-r bg-card py-3">
        <Link
          to={ROUTES.DASHBOARD}
          className="mb-4 flex h-8 w-8 items-center justify-center rounded-md text-[10px] font-bold tracking-tight hover:bg-accent"
          title="Dashboard"
        >
          MC
        </Link>
        <Link
          to={ROUTES.CATALOG}
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground',
            isActive(ROUTES.CATALOG) && 'bg-accent text-foreground',
          )}
          title="Catalog"
        >
          <BookOpen className="h-4 w-4" />
        </Link>
        {isAdmin && (
          <Link
            to={ROUTES.ADMIN}
            className={cn(
              'flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground',
              location.pathname.startsWith(ROUTES.ADMIN) && 'bg-accent text-foreground',
            )}
            title="Admin"
          >
            <Shield className="h-4 w-4" />
          </Link>
        )}
        <div className="flex-1" />
        <button
          onClick={() => navigate(ROUTES.PROFILE)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          title="Settings"
        >
          <Settings className="h-4 w-4" />
        </button>
        <button
          onClick={() => {
            useAuthStore.getState().logout()
            navigate(ROUTES.LOGIN)
          }}
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-destructive"
          title="Logout"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </aside>
    )
  }

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
            onClick={() => navigate(ROUTES.MISSION(mission.id))}
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
      <div className="border-t p-3">
        {user && (
          <div className="mb-2 flex items-center gap-2 px-1">
            <div className="flex-1 truncate">
              <p className="truncate text-xs font-medium">{user.display_name || user.email}</p>
              <p className="text-[10px] text-muted-foreground">
                {isAdmin ? 'Admin' : 'User'}
              </p>
            </div>
          </div>
        )}
        <div className="flex items-center justify-around">
          <button
            onClick={() => navigate(ROUTES.PROFILE)}
            className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>

          <NotificationDropdown />

          <button
            onClick={() => {
              useAuthStore.getState().logout()
              navigate(ROUTES.LOGIN)
            }}
            className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-destructive"
            title="Logout"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
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
