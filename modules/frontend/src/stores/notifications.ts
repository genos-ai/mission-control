import { create } from 'zustand'
import type { Notification } from '@/types'

interface NotificationState {
  notifications: Notification[]
  unreadCount: number

  add: (notification: Notification) => void
  markRead: (id: string) => void
  markAllRead: () => void
  clear: () => void
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  unreadCount: 0,

  add: (notification) =>
    set((state) => ({
      notifications: [notification, ...state.notifications].slice(0, 100),
      unreadCount: state.unreadCount + 1,
    })),

  markRead: (id) =>
    set((state) => {
      const target = state.notifications.find((n) => n.id === id)
      const wasUnread = target && !target.read
      return {
        notifications: state.notifications.map((n) =>
          n.id === id ? { ...n, read: true } : n,
        ),
        unreadCount: wasUnread ? Math.max(0, state.unreadCount - 1) : state.unreadCount,
      }
    }),

  markAllRead: () =>
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    })),

  clear: () => set({ notifications: [], unreadCount: 0 }),
}))
