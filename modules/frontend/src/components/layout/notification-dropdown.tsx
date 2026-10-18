import { useState, useRef } from 'react'
import { Bell } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StatusPill } from '@/components/ui/status-pill'
import { useClickOutside } from '@/hooks/use-click-outside'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'
import { useNotificationStore } from '@/stores/notifications'

export function NotificationDropdown() {
  const { notifications, unreadCount, markRead, markAllRead } = useNotificationStore()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useClickOutside(ref, () => setOpen(false), open)

  return (
    <div
      ref={ref}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <Button
        variant="ghost"
        size="icon"
        className="relative"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="h-[15px] w-[15px]" />
        {unreadCount > 0 && (
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-brand ring-[1.5px] ring-sidebar" />
        )}
      </Button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-card border border-panel-border bg-popover shadow-lg">
          <div className="flex items-center justify-between px-3 pb-1 pt-2.5">
            <span className="text-sm font-medium">Notifications</span>
            {unreadCount > 0 && (
              <Button variant="ghost" size="sm" onClick={markAllRead}>
                Mark all read
              </Button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto pb-1">
            {notifications.length === 0 ? (
              <p className="py-8 text-center text-sm text-subtle">No notifications</p>
            ) : (
              <div className="divide-y divide-border/60">
                {notifications.slice(0, 20).map((n) => (
                  <button
                    key={n.id}
                    className={cn(
                      'flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors duration-150 hover:bg-hover',
                      !n.read && 'bg-brand/5',
                    )}
                    onClick={() => markRead(n.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{n.title}</span>
                      {n.type === 'run_failed' || n.type === 'gate_approval' ? (
                        <StatusPill tone={n.type === 'run_failed' ? 'danger' : 'warning'} dot={false}>
                          {n.type.replace(/_/g, ' ')}
                        </StatusPill>
                      ) : (
                        <Badge>{n.type.replace(/_/g, ' ')}</Badge>
                      )}
                    </div>
                    <p className="line-clamp-2 text-xs text-muted-foreground">{n.body}</p>
                    <span className="font-mono text-2xs text-subtle">{formatUtc(n.created_at)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
