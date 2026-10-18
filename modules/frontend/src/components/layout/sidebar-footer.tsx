import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { LogOut, Moon, Sun } from 'lucide-react'

import { NotificationDropdown } from './notification-dropdown'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { useExecutions } from '@/hooks/use-executions'
import { formatElapsed, parseUtc } from '@/lib/format-date'
import { ROUTES } from '@/lib/constants'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/stores/theme'

export function SidebarFooter() {
  const navigate = useNavigate()
  const { user, isAdmin } = useAuthStore()
  const theme = useTheme((s) => s.theme)
  const toggleTheme = useTheme((s) => s.toggle)
  const nextThemeLabel = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'

  return (
    <div className="flex flex-col gap-1.5 border-t border-border p-2.5">
      <RunIndicator />
      {user && (
        <div className="flex items-center gap-2">
          <Link to={ROUTES.PROFILE} className="flex min-w-0 flex-1 items-center gap-2.5">
            <Avatar name={user.display_name || user.email} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">
                {user.display_name || user.email}
              </span>
              <span className="block text-2xs text-subtle">{isAdmin ? 'Admin' : 'User'}</span>
            </span>
          </Link>
          <NotificationDropdown />
          <Button variant="ghost" size="icon" aria-label={nextThemeLabel} title={nextThemeLabel} onClick={toggleTheme}>
            {theme === 'dark' ? <Sun className="h-[15px] w-[15px]" /> : <Moon className="h-[15px] w-[15px]" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Log out"
            title="Log out"
            className="hover:text-danger"
            onClick={() => {
              useAuthStore.getState().logout()
              navigate(ROUTES.LOGIN)
            }}
          >
            <LogOut className="h-[15px] w-[15px]" />
          </Button>
        </div>
      )}
    </div>
  )
}

/** Shown while runs are in progress; links to the longest-running one. */
function RunIndicator() {
  const { data } = useExecutions({ status: 'running', limit: 5 })
  const [now, setNow] = useState(() => Date.now())
  const runs = data?.executions ?? []

  useEffect(() => {
    if (runs.length === 0) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [runs.length])

  if (runs.length === 0) return null

  const longest = runs
    .filter((r) => r.started_at)
    .sort((a, b) => parseUtc(a.started_at!).getTime() - parseUtc(b.started_at!).getTime())[0]
  const elapsed = longest ? formatElapsed(now - parseUtc(longest.started_at!).getTime()) : null
  const label = `${data?.total ?? runs.length} ${(data?.total ?? runs.length) === 1 ? 'run' : 'runs'} in progress`
  const className =
    'flex items-center gap-2 rounded-control border border-panel-border bg-raised px-2.5 py-[7px] text-xs text-text-3'
  const content = (
    <>
      <span className="h-[7px] w-[7px] rounded-full bg-warning animate-pulse-dot motion-reduce:animate-none" />
      <span className="flex-1">{label}</span>
      {elapsed && <span className="font-mono text-2xs text-subtle">{elapsed}</span>}
    </>
  )

  return longest?.mission_id ? (
    <Link to={ROUTES.MISSION_RUN_LIVE(longest.mission_id, longest.id)} className={className}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  )
}
