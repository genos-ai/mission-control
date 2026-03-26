import { useState, useRef, useEffect } from 'react'
import { Bell } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useNotificationStore } from '@/stores/notifications'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function NotificationDropdown() {
  const { notifications, unreadCount, markRead, markAllRead } =
    useNotificationStore()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full left-1/2 mb-2 -translate-x-1/2 w-80 rounded-lg border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            {unreadCount > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                onClick={markAllRead}
              >
                Mark all read
              </Button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No notifications
              </p>
            ) : (
              notifications.slice(0, 20).map((n) => (
                <button
                  key={n.id}
                  className={`flex w-full flex-col gap-0.5 border-b px-3 py-2 text-left transition-colors hover:bg-accent last:border-b-0 ${
                    !n.read ? 'bg-primary/5' : ''
                  }`}
                  onClick={() => {
                    markRead(n.id)
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{n.title}</span>
                    <Badge
                      variant={
                        n.type === 'run_failed'
                          ? 'destructive'
                          : n.type === 'gate_approval'
                            ? 'warning'
                            : 'secondary'
                      }
                      className="text-[10px]"
                    >
                      {n.type.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {n.body}
                  </p>
                  <span className="text-[10px] text-muted-foreground">
                    {formatDistanceToNow(new Date(n.created_at), {
                      addSuffix: true,
                    })}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
